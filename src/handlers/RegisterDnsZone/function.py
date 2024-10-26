import os
import boto3
import json

from crhelper import CfnResource
from dataclasses import dataclass
from mypy_boto3_route53 import Route53Client
from mypy_boto3_route53.type_defs import ChangeBatchTypeDef, ChangeResourceRecordSetsRequestRequestTypeDef
from mypy_boto3_sts.type_defs import CredentialsTypeDef
from typing import Dict

from aws_lambda_powertools.logging import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.utilities.data_classes import (
    CloudFormationCustomResourceEvent,
    SNSEvent,
    event_source
)
helper = CfnResource(json_logging=True)

try:
    # FIXME: We should be able to set the service name from the environment.
    LOGGER = Logger(utc=True, service="RegisterDnsZone")
    STS_CLIENT = boto3.client('sts')
    CROSS_ACCOUNT_IAM_ROLE_NAME = os.environ.get('CROSS_ACCOUNT_IAM_ROLE_NAME', '')
    DNS_ROOT_ZONE_ID = os.environ.get('DNS_ROOT_ZONE_ID', '')
    DNS_ROOT_ZONE_ACCOUNT_ID = os.environ.get('DNS_ROOT_ZONE_ACCOUNT_ID', '')

    if CROSS_ACCOUNT_IAM_ROLE_NAME == '':
        raise ValueError("CROSS_ACCOUNT_IAM_ROLE_NAME must be provided")
    if DNS_ROOT_ZONE_ID == '':
        raise ValueError("DNS_ROOT_ZONE_ID must be provided")
    if DNS_ROOT_ZONE_ACCOUNT_ID == '':
        raise ValueError("DNS_ROOT_ZONE_ACCOUNT_ID must be provided")

except Exception as e:
    LOGGER.exception(e)
    helper.init_failure(e)


def _get_cross_account_credentials(
    account_id: str,
    role_name: str
) -> CredentialsTypeDef:
    '''Return the IAM role for cross-account access'''
    role_arn = 'arn:aws:iam::{}:role/{}'.format(account_id, role_name)
    try:
        response = STS_CLIENT.assume_role(
            RoleArn=role_arn,
            RoleSessionName='RegisterDnsZoneCrossAccount'
        )
    except Exception as e:
        LOGGER.exception(e)
        raise e

    return response['Credentials']


def _get_cross_account_route53_client(
    account_id: str,
    role_name: str
) -> Route53Client:
    '''Return a Route 53 client for cross-account access'''
    credentials = _get_cross_account_credentials(
        account_id,
        role_name
    )
    client = boto3.client(
        'route53',
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )

    return client


@helper.create
@helper.update
def create_or_update(event, _: LambdaContext):
    # Extract ResourceProperties from the event
    zone_name = event.get('ResourceProperties').get('ZoneName')
    nameservers = event.get('ResourceProperties').get('NameServers')

    if not zone_name:
        raise ValueError("ZoneName must be provided")
    if not nameservers:
        raise ValueError("NameServers must be provided")

    if not zone_name.endswith('.'):
        zone_name += '.'

    LOGGER.info(
        "Creating zone NS record",
        extra = {
            'zone_name': zone_name,
            'zone_id': DNS_ROOT_ZONE_ID,
            'nameservers': nameservers
        }
    )

    # Create the change batch for the NS record
    change_batch: ChangeBatchTypeDef = {
        'Comment': 'Upsert NS record for the zone {}'.format(zone_name),
        'Changes': [
            {
                'Action': 'UPSERT',
                'ResourceRecordSet': {
                    'Name': zone_name,
                    'Type': 'NS',
                    'TTL': 300,
                    'ResourceRecords': [{'Value': ns.strip()} for ns in nameservers]
                }
            }
        ]
    }

    change_args: ChangeResourceRecordSetsRequestRequestTypeDef = {
        'HostedZoneId': DNS_ROOT_ZONE_ID,
        'ChangeBatch': change_batch
    }


    route53_client = _get_cross_account_route53_client(
       DNS_ROOT_ZONE_ACCOUNT_ID,
       CROSS_ACCOUNT_IAM_ROLE_NAME
    )
    # Update the Route 53 hosted zone with the new NS record
    response = route53_client.change_resource_record_sets(**change_args)

    LOGGER.info("Change Info: {}".format(response['ChangeInfo']))

    return response['ChangeInfo']['Id']


@helper.delete
def delete(event, _: LambdaContext):
    # Extract ResourceProperties from the event
    zone_name = event.get('ResourceProperties').get('ZoneName')
    nameservers = event.get('ResourceProperties').get('NameServers')

    if not zone_name:
        raise ValueError("ZoneName must be provided")

    if not nameservers:
        raise ValueError("NameServers must be provided")

    LOGGER.info(
        "Deleting zone NS record",
        extra = {
            'zone_name': zone_name,
            'zone_id': DNS_ROOT_ZONE_ID,
            'nameservers': nameservers
        }
    )

    # Create the change batch to delete the NS record
    change_batch: ChangeBatchTypeDef = {
        'Changes': [
            {
                'Action': 'DELETE',
                'ResourceRecordSet': {
                    'Name': zone_name,
                    'Type': 'NS',
                    'TTL': 300,
                    'ResourceRecords': [{'Value': ns.strip()} for ns in nameservers]
                }
            }
        ]
    }

    route53_client = _get_cross_account_route53_client(
       DNS_ROOT_ZONE_ACCOUNT_ID,
       CROSS_ACCOUNT_IAM_ROLE_NAME
    )

    # Delete the NS record from the Route 53 hosted zone
    response = route53_client.change_resource_record_sets(
        HostedZoneId=DNS_ROOT_ZONE_ID,
        ChangeBatch=change_batch
    )

    LOGGER.info("Change Info: {}".format(response['ChangeInfo']))

def handler(event: Dict, context: LambdaContext):
    LOGGER.info("Event received", extra={'event': event})
    event_message = json.loads(event['Records'][0]['Sns']['Message'])
    LOGGER.info("Event message received", extra={'event_message': event_message})
    # FIXME: crhelper and PowerTools don't play well together so pass the raw data. We'll use
    # the event_source dataclass on this function for deserialization still though.
    helper(event_message, context)