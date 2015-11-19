########
# Copyright (c) 2015 Fastconnect - Atos. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License. 

# Third-party Imports
import boto.exception

# Cloudify imports
from ec2 import utils
from ec2 import constants
from ec2 import connection
from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
from cloudify.decorators import operation


@operation
def creation_validation(**_):
    """ This checks that all user supplied info is valid """

    if not ctx.node.properties['resource_id']:
        volume = None
    else:
        volume = _get_volume_object_by_id(
            ctx.node.properties['resource_id'])

    if ctx.node.properties['use_external_resource'] and not volume:
        raise NonRecoverableError(
            'External resource, but the supplied '
            'volume does not exist in the account.')

    if not ctx.node.properties['use_external_resource'] and volume:
        raise NonRecoverableError(
            'Not external resource, but the supplied '
            'volume exists.')

    if (ctx.node.properties['use_external_resource'] and volume and
        'available' not in volume.status):
        raise NonRecoverableError(
            'The supplied volume is not available in the account')


@operation
def create(**_):
    """This creates a volume in the connected account."""
    
    ec2_client = connection.EC2ConnectionClient().client()

        # Set device runtime property
    ctx.instance.runtime_properties['device'] = \
        ctx.node.properties['device']

    if _create_external_volume():
        return

    for property_key in constants.VOLUME_REQUIRED_PROPERTIES:
        utils.validate_node_property(property_key, ctx.node.properties)

    instance = (utils.get_target_external_resource_ids(
                'cloudify.aws.relationships.volume_attached_to_instance',
                ctx.instance))[0]

    zone = _get_instance_zone_from_id(instance)
    ctx.logger.debug('Attempting to create volume.')

    try:
        volume_object = ec2_client.create_volume(
            size=ctx.node.properties['size'],
            zone=zone,
            volume_type=ctx.node.properties['volume_type'])
    except (boto.exception.EC2ResponseError,
            boto.exception.BotoServerError) as e:
        raise NonRecoverableError('{0}'.format(str(e)))

    utils.set_external_resource_id(
        volume_object.id, ctx.instance, external=False)


@operation
def delete(**_):
    """This deletes a volume in the connected account."""
    volume = \
        utils.get_external_resource_id_or_raise(
            'delete volume', ctx.instance)

    if _delete_external_volume():
        return

    # Do not delete the volume if the user does not want to
    if ctx.node.properties['persistent']:
        return

    volume_object = _get_volume_object_by_id(volume)

    if not volume_object:
        ctx.logger.warning('Unable to find volume id.' +
             'The volume does not exist, or has already been deleted.')
        return

    ctx.logger.debug('Attempting to delete volume.')

    try:
        deleted = volume_object.delete()
    except boto.exception.EC2ResponseError as e:
        if 'attached' in e.message:
           return ctx.operation.retry(
                message='Volume still attached. Retrying...')
        else:
            raise NonRecoverableError('{0}'.format(str(e)))
    except boto.exception.BotoServerError as e:
        raise NonRecoverableError('{0}'.format(str(e)))

    if not deleted:
        raise NonRecoverableError(
            'Volume {0} deletion failed for an unknown reason.'
            .format(volume_object.id))

    volume = _get_volume_object_by_id(volume_object.id)

    if not volume:
        utils.unassign_runtime_property_from_resource(
            constants.EXTERNAL_RESOURCE_ID, ctx.instance)
    else:
        return ctx.operation.retry(
            message='Volume not deleted. Retrying...')


@operation
def attach(**_):
    """Attaches a volume  with an EC2 instance in the connected account."""

    ec2_client = connection.EC2ConnectionClient().client()

    volume = \
        utils.get_external_resource_id_or_raise(
            'attach volume', ctx.source.instance)
    instance_id  = \
        utils.get_external_resource_id_or_raise(
            'attach volume', ctx.target.instance)

    if _attach_external_volume_or_instance(volume):
        return

    ctx.logger.debug(
        'Attempting to attach volume {0} and instance {1}.'
        .format(volume, instance_id))

    try:
        ec2_client.attach_volume(
            instance_id=instance_id, 
            volume_id=volume,
            device=ctx.source.instance.runtime_properties['device'])
    except boto.exception.EC2ResponseError as e:
        if 'available' in e.message:
            ctx.operation.retry(
                message='Volume not available. Retrying...')
        else:
            raise NonRecoverableError('{0}'.format(str(e)))
    except boto.exception.BotoServerError as e:
        raise NonRecoverableError('{0}'.format(str(e)))

    ctx.logger.info(
        'Attached volume {0} with instance {1}.'
        .format(volume, instance_id))

    if 'volumes' not in ctx.target.instance.runtime_properties:
        ctx.logger.info('Creation volumes property for instance')
        ctx.target.instance.runtime_properties['volumes'] = []
    else:
        ctx.logger.info('Adding volume in volumes property for instance')

    ctx.target.instance.runtime_properties['volumes'].append(volume)


@operation
def detach(**_):
    """Detaches a volume from an EC2 instance in the connected account."""
    ec2_client = connection.EC2ConnectionClient().client()

    volume = \
        utils.get_external_resource_id_or_raise(
            'detach volume', ctx.source.instance)
    instance_id = \
        utils.get_external_resource_id_or_raise(
            'detach volume', ctx.target.instance)

    if _detach_external_volume_or_instance():
        return

    ctx.logger.debug('Detachin volume {0}'.format(volume))

    try:
        ec2_client.detach_volume(volume_id=volume)
    except (boto.exception.EC2ResponseError,
            boto.exception.BotoServerError) as e:
        raise NonRecoverableError('{0}'.format(str(e)))

    ctx.logger.info(
        'Detaching volume {0} from instance {1}.'
        .format(volume, instance_id))


def _create_external_volume():
    """Pretends to create volume but if it was
    not created by Cloudify, it just sets runtime_properties
    and exits the operation.

    :return False: Cloudify resource. Continue operation.
    :return True: External resource. Set runtime_properties. Ignore operation.
    """

    if not utils.use_external_resource(ctx.node.properties):
        return False

    volume = _get_volume_object_by_id(
        ctx.node.properties['resource_id'])
    if not volume:
        raise NonRecoverableError(
            'External volume was indicated, but the given '
            'volume does not exist in the account.')
    utils.set_external_resource_id(volume.id, ctx.instance)
    return True        


def _delete_external_volume():
    """Pretends to delete a volume but if it was
    not created by Cloudify, it just deletes runtime_properties
    and exits the operation.

    :return False: Cloudify resource. Continue operation.
    :return True: External resource. Unset runtime_properties.
        Ignore operation.
    """

    if not utils.use_external_resource(ctx.node.properties):
        return False

    utils.unassign_runtime_property_from_resource(
        constants.EXTERNAL_RESOURCE_ID, ctx.instance)
    return True


def _attach_external_volume_or_instance(volume):
    """Pretends to associate a Volume with an EC2 instance but if one
    was not created by Cloudify, it just sets runtime_properties
    and exits the operation.

    :return False: At least one is a Cloudify resource. Continue operation.
    :return True: Both are External resources. Set runtime_properties.
        Ignore operation.
    """

    if not utils.use_external_resource(ctx.source.node.properties) \
            or not utils.use_external_resource(
                ctx.target.node.properties):
        return False

    ctx.logger.info(
        'Either instance or volume is an external resource so not '
        'performing associate operation.')
    ctx.target.instance.runtime_properties['volumes'].append(volume)
    return True


def _get_instance_zone_from_id(instance_id):
    """To avoid availibilty zones error, we get the zone from the instance.

    :param instance_id: The ID of the connected instance.
    :return False: At least one is a Cloudify resource. Continue operation.
    """

    ec2_client = connection.EC2ConnectionClient().client()

    instance = ec2_client.get_only_instances(instance_id)[0]

    return instance.placement



def _detach_external_volume_or_instance():
    """Pretends to detach a volume but if it was
    not created by Cloudify, it just deletes runtime_properties
    and exits the operation.

    :return False: Cloudify resource. Continue operation.
    :return True: External resource. Unset runtime_properties.
        Ignore operation.
    """

    if not utils.use_external_resource(ctx.target.node.properties) \
            or not utils.use_external_resource(
                ctx.source.node.properties):
        return False

    ctx.logger.info(
        'Either instance or volume is an external resource so not '
        'performing detach operation.')
    ctx.target.instance.runtime_properties['volumes'].remove(volume)

    return True


def _get_volume_object_by_id(volume_id):
    """Returns the volume for a given volume id.

    :param volume_id: The ID of a volume.
    :returns The boto volume.
    """

    volume = _get_all_volumes(volume_id)

    return volume[0] if volume else volume


def _get_all_volumes(volume=None):
    """Returns a list of volume objects for a given volume_id.

    :param volume: The ID of a elastip.
    :returns A list of volume objects.
    :raises NonRecoverableError: If Boto errors.
    """

    ec2_client = connection.EC2ConnectionClient().client()

    try:
        volumes = ec2_client.get_all_volumes(volume)
    except boto.exception.EC2ResponseError as e:
        if 'InvalidVolume.NotFound' in e:
            volumes = ec2_client.get_all_volumes()
            utils.log_available_resources(volumes, ctx.logger)
        return None
    except boto.exception.BotoServerError as e:
        raise NonRecoverableError('{0}'.format(str(e)))

    return volumes