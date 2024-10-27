import json
import os
import boto3
import pytest

from aws_lambda_powertools.utilities.data_classes import (
    CloudFormationCustomResourceEvent,
    SNSEvent
)
from collections import namedtuple
from moto import mock_aws
from mypy_boto3_route53 import Route53Client
from mypy_boto3_sts import STSClient
from pytest_mock import MockerFixture
from types import ModuleType
from typing import cast, Generator, Tuple

from src.handlers.RegisterDnsZone.types import EventResourceProperties

FN_NAME = 'RegisterDnsZone'
DATA_DIR = './data'
FUNC_DATA_DIR = os.path.join(DATA_DIR, 'src/handlers', FN_NAME)
EVENT = os.path.join(FUNC_DATA_DIR, 'event.json')
EVENT_SCHEMA = os.path.join(FUNC_DATA_DIR, 'event.schema.json')
MESSAGE = os.path.join(FUNC_DATA_DIR, 'message.json')
#MESSAGE_SCHEMA = os.path.join(FUNC_DATA_DIR, 'message.schema.json')
DATA = os.path.join(FUNC_DATA_DIR, 'data.json')
DATA_SCHEMA = os.path.join(FUNC_DATA_DIR, 'data.schema.json')
OUTPUT = os.path.join(FUNC_DATA_DIR, 'output.json')
OUTPUT_SCHEMA = os.path.join(FUNC_DATA_DIR, 'output.schema.json')

#Fixtures
## AWS
@pytest.fixture
def mock_account_id() -> str:
    '''Mocked AWS Account ID'''
    account_id = '111111111111'
    os.environ['MOTO_ACCOUNT_ID'] = account_id
    return account_id

@pytest.fixture
def mock_cross_account_id() -> str:
    '''Mocked cross-account AWS Account ID'''
    return '999999999999'

@pytest.fixture()
def aws_credentials() -> None:
    '''Mocked AWS Credentials for moto.'''
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

@pytest.fixture()
def mocked_aws(aws_credentials):
    '''Mock all AWS interactions'''
    with mock_aws():
        yield

@pytest.fixture
def mock_route53_client(mocked_aws) -> Generator[Route53Client, None, None]:
    yield boto3.client('route53')

@pytest.fixture()
def mock_hosted_zone_id(mock_route53_client: Route53Client) -> str:
    '''Return the hosted zone'''
    r = mock_route53_client.create_hosted_zone(
        Name='example.com',
        CallerReference='test',
    )

    return r['HostedZone']['Id']


## Function
@pytest.fixture()
def mock_context() -> Tuple[str, str]:
    '''context object'''
    context_info = {
        'aws_request_id': '00000000-0000-0000-0000-000000000000',
        'function_name': FN_NAME,
        'invoked_function_arn': 'arn:aws:lambda:us-east-1:{}:function:{}'.format(
            mock_account_id,
            FN_NAME
        ),
        'memory_limit_in_mb': 128
    }

    Context = namedtuple('LambdaContext', context_info.keys())
    return Context(*context_info.values())


@pytest.fixture()
def mock_event(event: str = EVENT) -> SNSEvent:
    '''Return a test event'''
    with open(event) as f:
        return SNSEvent(json.load(f))


@pytest.fixture()
def mock_message(message: str = MESSAGE) -> CloudFormationCustomResourceEvent:
    '''Return a test message'''
    with open(message) as f:
        return CloudFormationCustomResourceEvent(json.load(f))

@pytest.fixture()
def mock_message_create(mock_message: CloudFormationCustomResourceEvent) -> CloudFormationCustomResourceEvent:
    '''Return a test message'''
    mock_message._data['RequestType']
    return mock_message

@pytest.fixture()
def mock_message_update(mock_message: CloudFormationCustomResourceEvent) -> CloudFormationCustomResourceEvent:
    '''Return a test message'''
    mock_message._data['RequestType'] = 'Update'
    return mock_message

@pytest.fixture()
def mock_message_delete(mock_message: CloudFormationCustomResourceEvent) -> CloudFormationCustomResourceEvent:
    '''Return a test message'''
    mock_message._data['RequestType'] = 'Delete'
    return mock_message

@pytest.fixture()
def mock_data(data: str = DATA) -> EventResourceProperties:
    '''Return test data'''
    with open(data) as f:
        # This is an actual data class unlike the type from aws_lambda_powertools
        return EventResourceProperties(**json.load(f))

@pytest.fixture()
def mock_fn(
    mocked_aws,
    mock_hosted_zone_id: str,
    mocker: MockerFixture,
) -> Generator[ModuleType, None, None]:
    '''Patch the environment variables for the function'''
    import src.handlers.RegisterDnsZone.function as fn

    mocker.patch(
        'src.handlers.RegisterDnsZone.function.DNS_ROOT_ZONE_ID',
        mock_hosted_zone_id
    )
    yield fn


# Tests


def test_create_or_update_as_create(
    mock_fn: ModuleType,
    mock_message_create: CloudFormationCustomResourceEvent,
    mock_data: EventResourceProperties,
    mock_context: Tuple[str, str],
    mock_route53_client: Route53Client,
    mock_hosted_zone_id: str,
    mocker: MockerFixture,
) -> None:
    event = mock_message_create._data
    event['ResourceProperties']['ZoneName'] = mock_data.ZoneName
    event['ResourceProperties']['NameServers'] = mock_data.NameServers

    # Call the create_or_update function
    mock_fn.create_or_update(event, mock_context)

    # Verify the NS record was created
    response = mock_route53_client.list_resource_record_sets(
        HostedZoneId=mock_hosted_zone_id
    )

    # check response
    records = response.get('ResourceRecordSets')
    assert records is not None

    # check records
    record = [ rr for rr in records if rr['Name'].rstrip('.') == mock_data.ZoneName ]
    assert len(record) == 1
    assert record[0]['Name'].rstrip('.') == mock_data.ZoneName
    assert record[0]['Type'] == 'NS'

    nameservers = cast(list, mock_data.NameServers)
    values = [ rr.get('Value') for rr in record[0]['ResourceRecords'] ]
    assert nameservers[0] in values
    assert nameservers[1] in values
    assert nameservers[2] in values
    assert nameservers[3] in values

def test_create_or_update_as_update(
    mock_fn: ModuleType,
    mock_context: Tuple[str, str],
    mock_route53_client: Route53Client,
    mock_message_update: CloudFormationCustomResourceEvent,
    mock_data: EventResourceProperties,
    mock_hosted_zone_id: str,
    mocker: MockerFixture,
) -> None:
    event = mock_message_update._data
    event['ResourceProperties']['ZoneName'] = mock_data.ZoneName
    event['ResourceProperties']['NameServers'] = mock_data.NameServers

    # Call the create_or_update function
    mock_fn.create_or_update(event, mock_context)

    # Verify the NS record was created
    response = mock_route53_client.list_resource_record_sets(
        HostedZoneId=mock_hosted_zone_id
    )

    # check response
    records = response.get('ResourceRecordSets')
    assert records is not None

    # check records
    record = [ rr for rr in records if rr['Name'].rstrip('.') == mock_data.ZoneName ]
    assert len(record) == 1
    assert record[0]['Name'].rstrip('.') == mock_data.ZoneName
    assert record[0]['Type'] == 'NS'

    nameservers = cast(list, mock_data.NameServers)
    values = [ rr.get('Value') for rr in record[0]['ResourceRecords'] ]
    assert nameservers[0] in values
    assert nameservers[1] in values
    assert nameservers[2] in values
    assert nameservers[3] in values

def test_delete(
    mock_fn: ModuleType,
    mock_context: Tuple[str, str],
    mock_route53_client: Route53Client,
    mock_message_create: CloudFormationCustomResourceEvent,
    mock_message_delete: CloudFormationCustomResourceEvent,
    mock_data: EventResourceProperties,
    mock_hosted_zone_id: str,
    mocker: MockerFixture,
) -> None:

    # Create record to be deleted
    create_event = mock_message_create._data
    create_event['ResourceProperties']['ZoneName'] = mock_data.ZoneName
    create_event['ResourceProperties']['NameServers'] = mock_data.NameServers

    # Call the create_or_update function
    mock_fn.create_or_update(create_event, mock_context)

    # Verify the NS record was created
    response = mock_route53_client.list_resource_record_sets(
        HostedZoneId=mock_hosted_zone_id
    )

    # Create delete event
    delete_event = mock_message_delete._data
    delete_event['ResourceProperties']['ZoneName'] = mock_data.ZoneName
    delete_event['ResourceProperties']['NameServers'] = mock_data.NameServers

    # Call the delete function
    mock_fn.delete(delete_event, mock_context)

    # Query zone records for verification
    response = mock_route53_client.list_resource_record_sets(
        HostedZoneId=mock_hosted_zone_id
    )

    records = response['ResourceRecordSets']
    for _rr in records:
        assert _rr['Name'].rstrip('.') != mock_data.ZoneName

@pytest.mark.skip(reason='Test hangs pytest')
def test_handler(
    mock_fn: ModuleType,
    mock_context: Tuple[str, str],
    mock_event: CloudFormationCustomResourceEvent,
    mock_message_create: CloudFormationCustomResourceEvent,
    mock_data: EventResourceProperties,
    mocker: MockerFixture,
) -> None:

    mock_message_create._data['ResourceProperties']['ZoneName'] = mock_data.ZoneName
    mock_message_create._data['ResourceProperties']['NameServers'] = mock_data.NameServers
    mock_event._data['Records'][0]['Sns']['Message'] = json.dumps(mock_message_create._data)

    mocker.patch(
        'src.handlers.RegisterDnsZone.function.create_or_update',
        return_value=None
    )

    # Call the handler function
    mock_fn.handler(mock_event, mock_context)

    # Verify the NS record was created
    response = mock_fn.create_or_update.call_args
    assert response is not None
    assert response[0][0] == mock_event._data
    assert response[0][1] == mock_context