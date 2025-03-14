# Storage Backends for changedetection.io

This module provides different storage backends for changedetection.io, allowing you to store data in various systems:

- **FileSystemStorage**: The default storage backend that stores data on the local filesystem.
- **MongoDBStorage**: Stores data in a MongoDB database.
- **S3Storage**: Stores data in an Amazon S3 bucket.

## Usage

The storage backend is automatically selected based on the datastore path provided when initializing the application:

- For filesystem storage (default): `/datastore`
- For MongoDB storage: `mongodb://username:password@host:port/database`
- For S3 storage: `s3://bucket-name/optional-prefix`

## Configuration

### Filesystem Storage

The default storage backend. Simply specify a directory path:

```
changedetection.io -d /path/to/datastore
```

### MongoDB Storage

To use MongoDB storage, specify a MongoDB connection URI:

```
changedetection.io -d mongodb://username:password@host:port/database
```

Make sure to install the required dependencies:

```
pip install -r requirements-storage.txt
```

### Amazon S3 Storage

To use S3 storage, specify an S3 URI:

```
changedetection.io -d s3://bucket-name/optional-prefix
```

Make sure to:
1. Install the required dependencies: `pip install -r requirements-storage.txt`
2. Configure AWS credentials using environment variables or IAM roles:
   - Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables
   - Or use an IAM role when running on AWS EC2/ECS/EKS

## Custom Storage Backends

You can create custom storage backends by:

1. Subclassing the `StorageBase` abstract class in `storage_base.py`
2. Implementing all required methods
3. Adding your backend to the `storage_factory.py` file