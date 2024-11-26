## IoT Automotive Cloud Demo

# Deploying the demo-iot-automotive-cloud with Rich Sensor Data Preview Feature

This README file provides a step-by-step guide for deploying the demo-iot-automotive-cloud project with the Rich Sensor Data Preview feature enabled. The guide assumes that you have basic knowledge of AWS, CDK, and Python.

## Prerequisites
sudo apt install python
 
- Ensure your AWS accounts are fully allow-listed.
- All deployments are restricted to the regions where AWS IoT FleetWise is available.

This is the list of pre requisites for completing the installation and deployment:

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [AWS CDK CLI](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html)
- [Node.js and NPM](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm)
- [Docker](https://docs.docker.com/engine/install/) for the deployment of the Grafana stack
- Python 3, Pip 3 & VEnv


Install the AWS CDK and Yarn globally using npm (important not do this in the python venv!):

```bash
npm install -g aws-cdk
npm install -g yarn
```

### Clean Up if you previously used AWS IoT FleetWise in your AWS Account

If you previously registered your account with the FleetWise service, you need to delete the existing **AWSServiceRoleForIoTFleetWise** Role. 

Go to the IAM console in your account, find the Role **AWSServiceRoleForIoTFleetWise** and delete it. 

This will enable you to register for the **Gamma** service.

### Build and install the **cdk-aws-iotfleetwise** library

> **Why do we need to build the **cdk-aws-iotfleetwise** library?**
>
> The current version of the CDK FleetWise library (published here: https://pypi.org/project/cdk-aws-iotfleetwise/) doesn't include the new FleetWise API model (under testing).
>
> We have copied locally temporarily in order to create a local version.
>
> **This work is temporary until the Rich Sensor Data feature is released.**

Open a terminal and execute the following commands:

```bash
python3 -m venv ~/.venv-fwe
source ~/.venv-fwe/bin/activate

cd ./src/cdk-aws-iotfleetwise

yarn install # Done in 775.03s

# build the cdk-aws-iotfleetwise lib - needs to be done every time the lib changes!
npx projen # Done in 863.13s.
npx projen compile
npx projen package:python

deactivate
cd ../..
```

At the end of the process, a packaged version of the cdk-aws-iotfleetwise will be created in:

- lib/cdk-aws-iotfleetwise/dist/python/cdk-aws-iotfleetwise-0.0.0.tar.gz

You can the install it like any other Python package using pip.

## Deploying the stack 

### Setting environment variables

```bash
export AWS_PROFILE="default"
export AWS_DEFAULT_REGION=$(aws configure get region --profile ${AWS_PROFILE})
export AWS_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text --profile ${AWS_PROFILE})

echo "PROFILE : $AWS_PROFILE"
echo "ACCOUNT : $AWS_DEFAULT_ACCOUNT"
echo "REGION  : $AWS_DEFAULT_REGION"
```

Make sure your AWS account and region are set up correctly and you have the appropriate keys exported.

### Deploying the Yocto Image

Before deploying the main CDK app, navigate to the [demo-iot-automotive-embeddedlinux-image](https://github.com/aws4embeddedlinux/demo-iot-automotive-embeddedlinux-image) repository.

Then follow the instructions in the [README](https://github.com/aws4embeddedlinux/demo-iot-automotive-embeddedlinux-image/README.md) to create the Yocto image. 

This will generate a `yoctoSdkS3Path` which will be used in a later step. 

You need to look up the S3 URI manually in S3 named: "nxpgoldboxbigapipeline-pipelineoutput***"

```bash
export YOCTO_SDK_S3_BUCKET_ARN=$(aws cloudformation describe-stacks --stack-name biga-build-nxp-goldbox --output text --query "Stacks[0].Outputs[?OutputKey=='BuildOutput'].OutputValue")
export YOCTO_SDK_S3_BUCKET=${YOCTO_SDK_S3_BUCKET_ARN##*:}
echo $YOCTO_SDK_S3_BUCKET
```

The value should look like : `nxpgoldboxbigapipeline-demoartifactxxxxxxxxx-yyyyyyyyyy`.

```bash
export YOCTO_SDK_SCRIPT_NAME=$(aws s3api list-objects --bucket $YOCTO_SDK_S3_BUCKET --output text --query 'Contents[?starts_with(Key, `fsl`) == `true`][Key,LastModified] | sort_by(@, &[1])[0:1][0]')
echo $YOCTO_SDK_SCRIPT_NAME
```

The value should look like : `fsl-auto-glibc-x86_64-cortexa53-crypto-toolchain-38.0.sh`.

### Creating an S3 Bucket for the Build Artifacts

Create an S3 bucket for storing the aws-iot-fleetwise-edge code and `rosbag2_rich_data_demo` rich sensor data artifacts:

```bash
export FWE_BUILD_ARTIFACTS_BUCKET="${AWS_DEFAULT_ACCOUNT}-${AWS_DEFAULT_REGION}-fwe-rs-build-artifacts"
echo $FWE_BUILD_ARTIFACTS_BUCKET

aws s3 mb s3://${FWE_BUILD_ARTIFACTS_BUCKET}
```

### Preparing the Amazon IoT Fleetwise for vision system data collection and transformation artifacts

Prepare the `rosbag2_rich_data_demo.tar.bz2`.

Upload these artifacts to the S3 bucket:

```bash

aws s3 cp s3://aws-iot-fleetwise/rosbag2_vision_system_data_demo.db3 .

tar -cvjSf rosbag2_vision_system_data_demo.tar.bz2 rosbag2_vision_system_data_demo.db3

aws s3 cp rosbag2_vision_system_data_demo.tar.bz2 s3://$FWE_BUILD_ARTIFACTS_BUCKET
aws s3 cp rosbag2_rich_data_demo.tar.bz2 s3://$FWE_BUILD_ARTIFACTS_BUCKET
```

Alternatively, follow the instructions [here](https://github.com/aws/aws-iot-fleetwise-edge) to get `aws-iot-fleetwise-edge` code and `rosbag2_vision_system_data_demo.tar.bz2`.

### Deploying the Main CDK App with Additional Context

Now, let's proceed with the main CDK stack creation using the following commands:

```bash
cd cdk
python3 -m venv ~/.venv-cdk
source ~/.venv-cdk/bin/activate

pip install -r ./requirements.txt
pip install ../src/cdk-aws-iotfleetwise/dist/python/cdk_aws_iotfleetwise-0.0.0.tar.gz 

# only required once
cdk bootstrap

# Set the FleetWise Edgs Config 
# Since FWE requires specific configuration based on the region and the environment it's running, we will need to configure it by first exporting the appropriate env variables and then generating the `fwe-config.yaml`:

export GGV2_INTERFACE_NAME=vcan0

export GGV2_THING_NAME="vCar"
export GGV2_THING_GROUP="EmbeddedLinuxFleet"

export GGV2_ACCOUNT=$(aws sts get-caller-identity --query Account --output text --profile ${AWS_PROFILE})
export GGV2_REGION=$(aws configure get region --profile ${AWS_PROFILE} )
export GGV2_DATA_EP=$(aws --output text iot describe-endpoint --profile ${AWS_PROFILE} --endpoint-type iot:Data-ATS           --query 'endpointAddress')
export GGV2_CRED_EP=$(aws --output text iot describe-endpoint --profile ${AWS_PROFILE} --endpoint-type iot:CredentialProvider --query 'endpointAddress')
export GGV2_TES_RALIAS=$(aws cloudformation describe-stacks --stack-name biga-greengrass-fleet-provisoning --query 'Stacks[0].Outputs[?OutputKey==`GGTokenExchangeRoleAlias`].OutputValue' --output text)

export TOPIC_PREFIX='$aws/iotfleetwise/vehicles/'$GGV2_THING_NAME

envsubst < "../config/greengrass/fleetwise_edge_connector/fwe-config.yaml.template" > "../config/greengrass/fleetwise_edge_connector/fwe-config.yaml"
envsubst < "../config/greengrass/deployment.json.template" > "../config/greengrass/deployment.json"

# deploy API Gateway Endpoint stack
cdk deploy biga-vision-api \
    --require-approval never

# Create the Grafana Chart JSON file from the template, based on the API Gateway endpoint
export API_ENDPOINT_PREFIX=$(aws cloudformation describe-stacks --stack-name biga-vision-api --output text --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue")
echo "API_ENDPOINT_PREFIX  : $API_ENDPOINT_PREFIX"
envsubst < "../config/grafana/provisioning/dashboards/IndividualSignalAnalysis.json.template" > "../config/grafana/provisioning/dashboards/IndividualSignalAnalysis.json"

# deploy stack
cdk deploy --all \
    --require-approval never
```

### Deploying the AWS GreenGrass Components

After successful stack deployment, the Greengrass components are built by CodePipeline. 

When the onboarding of the device is successful, a deployment of those components needs to be executed:

```bash
aws greengrassv2 create-deployment --cli-input-json file://../config/greengrass/deployment.json
```

## Steps needed to create a new Lambda layer zip

If in need to work with a version of boto3 not yet supported by the Lambda runtime, you can use your desired boto3 SDK version with the following commands:

```bash
cd src/cdk-aws-iotfleetwise
mkdir -p boto3-layer/python
pip3 install boto3 -t boto3-layer/python
cd boto3-layer
zip -r boto3-layer.zip .
rm -rf boto3-layer
```

## Cleanup

```bash
cdk destroy --all --force

aws iotfleetwise delete-signal-catalog --name FleetWiseSignalCatalog
```

## Known issues
- The update operation is not implemented for all Custom Resources. So you can still experience failed updates, failed delete etc.
- This integration is still under heavy development. We will continue doing bug fixes and improvements.
- Not possible at the moment to update the fleetwise stack, need to manually delete biga-aws-iotfleetwise stack in CloudFormation, which will fail, mark to keep resources and delete again.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

