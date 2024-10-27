import os
import boto3
import json

from crhelper import CfnResource
from mypy_boto3_route53 import Route53Client
from mypy_boto3_route53.type_defs import (
    ChangeBatchTypeDef,
    ChangeResourceRecordSetsRequestRequestTypeDef
)
from typing import Dict

from aws_lambda_powertools.logging import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
helper = CfnResource(json_logging=True)

try:
    # FIXME: We should be able to set the service name from the environment.
    LOGGER = Logger(utc=True, service="RegisterDnsZone")
    RT53_CLIENT: Route53Client = boto3.client('route53')
    DNS_ROOT_ZONE_ID = os.environ.get('DNS_ROOT_ZONE_ID', '')
    if DNS_ROOT_ZONE_ID == '':
        raise ValueError("DNS_ROOT_ZONE_ID must be provided")

except Exception as e:
    LOGGER.exception(e)
    helper.init_failure(e)


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

    # Update the Route 53 hosted zone with the new NS record
    response = RT53_CLIENT.change_resource_record_sets(**change_args)

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

    # Delete the NS record from the Route 53 hosted zone
    response = RT53_CLIENT.change_resource_record_sets(
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