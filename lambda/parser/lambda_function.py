# MIT License
# Copyright (c) 2023 [Your Name or Organization]
# See LICENSE file for details

import json
import boto3
import email
from email import policy
from email.parser import BytesParser
import requests  # For HTTP POST requests
import uuid
import os

# Initialize clients
s3_client = boto3.client('s3')

# Get domain name from environment variable
domain_name = os.environ.get('DOMAIN_NAME', 'emailtowebhook.com')

def lambda_handler(event, context):
    # Define the bucket for webhook storage
    webhook_bucket_name = 'email-webhooks-bucket-3rfrd'
    attachments_bucket_name = 'email-attachments-bucket-3rfrd'
    # Parse the S3 event
    for record in event['Records']:
        email_bucket_name = record['s3']['bucket']['name']
        email_object_key = record['s3']['object']['key']

        # Get the email object from S3
        response = s3_client.get_object(Bucket=email_bucket_name, Key=email_object_key)
        raw_email = response['Body'].read()

        print(f"Received email from {email_bucket_name}/{email_object_key}")
        print(f"Email content: {raw_email}")
        # Parse the email
        msg = BytesParser(policy=policy.default).parsebytes(raw_email)

        # Extract email details
        sender = msg['From']
        recipient = msg['To']
        subject = msg['Subject']
        body = ""
        attachments = []

        # Extract the domain from the sender
        sender_domain = sender.split('@')[-1]

        print(f"Sender: {sender}")
        print(f"Recipient: {recipient}")
        # Retrieve webhook URL for the domain from the S3 bucket
        webhook_key = recipient.split('@')[-1]  # Assuming each domain's webhook is stored with the domain name as the key
        print(f"Webhook key: {webhook_key}")
        try:
            webhook_response = s3_client.get_object(Bucket=webhook_bucket_name, Key=webhook_key)
            webhook_data = json.loads(webhook_response['Body'].read())
            webhook_url = webhook_data['webhook']
        except Exception as e:
            print(f"Error retrieving webhook for domain {sender_domain}: {e}")
            return {
                'statusCode': 500,
                'body': f"Webhook for domain {sender_domain} not found or error occurred."
            }

        # Extract email body and attachments
        if msg.is_multipart():
            for part in msg.iter_parts():
                content_type = part.get_content_type()
                content_disposition = part.get_content_disposition()

                if content_type == "text/plain":
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
                elif content_type == "text/html" and not body:  # Use HTML if plain text is unavailable
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
                elif content_disposition and "attachment" in content_disposition:
                    # Process attachments
                    attachment_data = part.get_payload(decode=True)
                    attachment_name = part.get_filename()

                    # generate random guid and concatenate with attachment name

                    display_key= f"{uuid.uuid4().hex}/{attachment_name}"

                    attachment_key = f"attachments/{display_key}"
                    s3_client.put_object(
                        Bucket=attachments_bucket_name,
                        Key=attachment_key,
                        Body=attachment_data
                    )

                    public_url = f"https://attachments.{domain_name}/{display_key}"
                    attachments.append({
                        "filename": attachment_name,
                        "public_url": public_url,
                        "content_type": content_type
                    })
                elif "Content-ID" in part and not content_disposition:  # Process inline images
                    content_id = part['Content-ID'].strip('<>')
                    inline_image_data = part.get_payload(decode=True)
                    inline_image_name = part.get_filename() or f"inline_{content_id}.png"

                    inline_image_key = f"inline_images/{inline_image_name}"
                    s3_client.put_object(
                        Bucket=attachments_bucket_name,
                        Key=inline_image_key,
                        Body=inline_image_data
                    )

                    inline_image_url = f"https://{attachments_bucket_name}.s3.amazonaws.com/{inline_image_key}"

                    # Replace cid: references in the HTML body with the public URL
                    if body:
                        body = body.replace(f"cid:{content_id}", inline_image_url)
        else:
            body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8")

        # Construct payload
        parsed_email = {
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "attachments": attachments
        }

        # Send HTTP POST request to the webhook
        try:
            response = requests.post(webhook_url, json=parsed_email, timeout=10)
            response.raise_for_status()
            print(f"Data sent to webhook {webhook_url} successfully.")
        except requests.exceptions.RequestException as e:
            print(f"Error sending data to webhook {webhook_url}: {e}")
            return {
                'statusCode': 500,
                'body': f"Error sending data to webhook {webhook_url}: {str(e)}"
            }

    return {
        'statusCode': 200,
        'body': "Email processed and data sent to webhook successfully."
    }
