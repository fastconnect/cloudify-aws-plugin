cloudify-aws-plugin
===================

A Cloudify Plugin that provisions resources in Amazon Web Services

* Master [![Build Status](https://travis-ci.org/cloudify-cosmo/cloudify-aws-plugin.svg?branch=master)](https://travis-ci.org/cloudify-cosmo/cloudify-aws-plugin)

## Usage
See [AWS Plugin](http://getcloudify.org/guide/3.2/plugin-aws.html)

# Requirements
boto AWS Python Library version 2.34.0

boto ec2 connection EC2Connection (AWS) APIVersion = '2014-10-01'

How-to: use the volume node
===========================

This custom plugin implements a volume node for AWS EC2.
To add a volume to an instance node, just make a relationship cloudify.aws.relationships.volume_attached_to_instance between them.
The availability zone is chosen based on the attached machine.

cloudify.aws.nodes.Volume
-------------------------

Derived From: *cloudify.nodes.Volume*

Properties:
^^^^^^^^^^^

* **size:** The size in GiB of the volume to create in AWS.
* **volume_type:** The type of the volume. Valid values are 'standard (default) | io1 | gp2'.
* **persistent:** Indicates if the volume should be persistent. Default: true (the volume will NOT be deleted at deprovisioning).
* **device:** The device where the disk will be mounted (/dev/sdg, etc.).
* **use_external_resource:** Specify if the volume already exists.
* **resource_id:** The resource id of the volume.
* **aws_config:** The AWS config to use.

Mapped Operations:
^^^^^^^^^^^^^^^^^^

* aws.ec2.volume.create creates the volume.
* aws.ec2.volume.delete deletes the volume.

cloudify.aws.relationships.volume_attached_to_instance
------------------------------------------------------

The relationship to use to attach a volume to an instance.

Mapped Operations:
^^^^^^^^^^^^^^^^^^

* aws.ec2.volume.attach attach a volume to an instance.
* aws.ec2.volume.detach detach a volume from an instance.

Example
-------
  
```
  instance_disk:
    type: cloudify.aws.nodes.Volume
    properties:
      size: 50
      persistent: false
      device: '/dev/sdf'
      resource_id: 'instance_disk'
    relationships:
      - type: cloudify.aws.relationships.volume_attached_to_instance
        target: instance
```

Limitations
===========

* The device name MUST follow the AWS convention: http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/device_naming.html
* The snapshot capability is not implemented.
* You cannot specify multiple volumes in one node.
* You have to package the plugin to use in you blueprint. **Do not forget** to change the imports,
 and plugins directives in your blueprints, and to specify the right plugin.yaml.
* The format, mount, and filesystem has to be done by the user.
* If you reuse a volume, be sure the instance is placed in the same availability zone.
* The encryption is not supported.