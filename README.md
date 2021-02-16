# action-beanstalk-deploy
GitHub action for AWS Elastic Beanstalk deployment


# Introduction
This action manages a full Beanstalk environment update. The whole steps are listed below:

## Build and upload docker images
This step builds docker images, given by a list of container configurations.
The config file will be read from a config file, the path can be set with `config_path`.
An example of the configuration file is shown below.
This step will only be executed if the `build_and_upload_image` key is set in the configuration file.

## Create and upload deployment archive (Dockerrun.aws.json)
Create `deploy-CommitSHA.zip` and upload it to the specified application version bucket.
The commit SHA in the filename is the SHA which triggered the workflow (e.g. `796a30eac5a3bb2da4e90d79366f6760e16ac91a`).
This zip archive contains only the `Dockerrun.aws.json` at this moment.

## Create Beanstalk application version
This action uses a different Beanstalk application for each environment, e.g. (dev, test, live).

## Update Beanstalk environment
Update the given Beanstalk environment with the given version label, which was created before.

## Wait until the deployment is finished
The default settings are to wait until the deployment process is finished and the Beanstalk environment is in ready and healthy state.


# Config example
`dev.json`:
```json
{
  "build_and_upload_image": true,
  "application_name": "my-sample-application-dev",
  "environment_name": "sample-application-dev",
  "application_version_bucket": "sample-application-version-bucket-dev",
  "containers": [
    {
      "dockerfile": "docker/Dockerfile",
      "name": "sample-application",
      "image_base_name": "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository",
      "ports": [
        {
          "host": 80,
          "container": 80
        }
      ]
    }
  ]
}
```

`test.json`:
```json
{
  "build_and_upload_image": false,
  "application_name": "my-sample-application-test",
  "environment_name": "sample-application-test",
  "application_version_bucket": "sample-application-version-bucket-test",
  "containers": [
    {
      "dockerfile": "docker/Dockerfile",
      "name": "sample-application",
      "image_base_name": "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository",
      "ports": [
        {
          "host": 80,
          "container": 80
        }
      ]
    }
  ]
}
```

# Defaults
Variable | Default
---------|--------
`aws_region` | `eu-central-1`
`version_label` | `${{ github.sha }}`
`version_description` | `"GitHub Action #${{ github.run_number }}"`
`wait_for_deployment` | `true`
`base_path` | `${{ github.workspace }}`

# Usage

See [action.yml](action.yml).

Basic (with default values):
```yaml
steps:
  - name: Deploy
    uses: moneymeets/action-beanstalk-deploy@master
    with:
      aws_access_key_id: ${{ secrets.AWS_ACCESS_KEY_ID }}
      aws_secret_access_key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      config_path: "${{ format('configs/{0}.json', github.event.deployment.environment) }}"
```

With full list of parameters:
```yaml
steps:
  - name: Deploy
    uses: moneymeets/action-beanstalk-deploy@master
    with:
      aws_access_key_id: ${{ secrets.AWS_ACCESS_KEY_ID }}
      aws_secret_access_key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      config_path: "${{ format('configs/{0}.json', github.event.deployment.environment) }}"
      aws_region: eu-central-1
      version_label: CustomVersionLabel
      version_description: CustomVersionDescription
      base_path: ${{ github.workspace }}
      wait_for_deployment: false
```

# Local testing
You can test the action python script, by settings the necessary environment variables.
The local image will be built with a suffix `-ci`.

Make sure that valid AWS credentials are exported into your profile, or located in `~/.aws/credentials` file.

```bash
export VERSION_LABEL=SampleVersionLabel
export VERSION_DESCRIPTION=SampleVersionDescription
export BASE_PATH=../sample-application
export CONFIG_PATH=../sample-application/.config/dev.json
export WAIT_FOR_DEPLOYMENT=false

python action.py
```
