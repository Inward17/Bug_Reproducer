import boto3
import json

def lambda_handler(event, context):
    """Example Lambda function that reads from S3 and writes to DynamoDB."""
    
    # Initialize AWS clients
    s3 = boto3.client('s3')
    dynamodb = boto3.resource('dynamodb')
    
    # Read from S3
    bucket_name = 'my-data-bucket'
    key = 'input/data.json'
    response = s3.get_object(Bucket=bucket_name, Key=key)
    data = json.loads(response['Body'].read())
    
    # Write to DynamoDB
    table = dynamodb.Table('my-table')
    table.put_item(Item={
        'id': data['id'],
        'value': data['value']
    })
    
    return {
        'statusCode': 200,
        'body': json.dumps('Success')
    }
