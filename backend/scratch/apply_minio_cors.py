import boto3
from botocore.client import Config
import os
from dotenv import load_dotenv

load_dotenv()

def apply_cors():
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.getenv("MINIO_BUCKET", "contracts")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # Normalize endpoint
    if not endpoint.startswith("http"):
        protocol = "https" if secure else "http"
        endpoint = f"{protocol}://{endpoint}"

    print(f"Connecting to MinIO at {endpoint}...")

    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1' # Default for MinIO
    )

    cors_configuration = {
        'CORSRules': [
            {
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'PUT', 'POST', 'DELETE', 'HEAD'],
                # Allow both development and production ports
                'AllowedOrigins': ['http://localhost:5173', 'http://localhost:3000', '*'],
                'ExposeHeaders': ['ETag'],
                'MaxAgeSeconds': 3000
            }
        ]
    }

    try:
        s3.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors_configuration)
        print(f"✅ Successfully applied CORS policy to bucket '{bucket}'")
    except Exception as e:
        print(f"❌ Failed to apply CORS policy: {e}")

if __name__ == "__main__":
    apply_cors()
