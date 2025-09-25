# Diagram Upload API Implementation

## Overview

This document describes the implementation of diagram upload functionality for the VidyaAI assignment system. The API provides endpoints for uploading, serving, and deleting diagram files used in assignment questions.

## New Endpoints

### 1. Upload Diagram
```
POST /api/assignments/upload-diagram
```

**Purpose**: Upload a diagram/image file for assignment questions

**Parameters**:
- `file` (multipart/form-data): The image file to upload
- `assignment_id` (optional query param): Associate file with specific assignment

**Supported File Types**:
- PNG, JPG, JPEG, GIF, SVG images
- PDF files
- Maximum size: 10MB

**Response**:
```json
{
  "file_id": "uuid-string",
  "filename": "original_filename.png",
  "content_type": "image/png",
  "size": 1024567,
  "s3_key": "assignments/{assignment_id}/diagrams/{file_id}.png",
  "url": "presigned-s3-url",
  "uploaded_at": "2024-01-01T12:00:00Z"
}
```

**Security**:
- Requires Firebase authentication
- If `assignment_id` provided, verifies user owns assignment or has edit access
- Validates file type and size

### 2. Serve Diagram
```
GET /api/assignments/diagrams/{file_id}?assignment_id={assignment_id}
```

**Purpose**: Get access to uploaded diagram file

**Parameters**:
- `file_id` (path): The unique file identifier
- `assignment_id` (optional query): Assignment context for access control

**Response**:
- HTTP 302 redirect to presigned S3 URL (expires in 1 hour)
- Direct access to the image file

**Security**:
- Requires Firebase authentication
- Verifies user has access to the assignment (if provided)
- Only returns files user has permission to view

### 3. Delete Diagram
```
DELETE /api/assignments/diagrams/{file_id}?assignment_id={assignment_id}
```

**Purpose**: Delete uploaded diagram file

**Parameters**:
- `file_id` (path): The unique file identifier
- `assignment_id` (optional query): Assignment context for access control

**Response**:
```json
{
  "message": "Diagram deleted successfully",
  "file_id": "uuid-string",
  "deleted_keys": ["s3-key1", "s3-key2"]
}
```

**Security**:
- Requires Firebase authentication
- Verifies user owns assignment or has edit access
- Only deletes files user has permission to manage

## Storage Structure

Files are organized in S3 with the following structure:

```
assignments/
  {assignment_id}/
    diagrams/
      {file_id}.{extension}

users/
  {user_id}/
    diagrams/
      {file_id}.{extension}
```

- **Assignment-specific files**: Stored under `assignments/{assignment_id}/diagrams/`
- **User files**: Stored under `users/{user_id}/diagrams/` if no assignment context

## File Management

### File ID Generation
- Uses UUID4 for unique file identifiers
- Preserves original file extension
- Files can be located by trying multiple extensions

### Access Control
1. **Upload**: User must own assignment or have edit permission
2. **View**: User must have any access to assignment (view/edit)
3. **Delete**: User must own assignment or have edit permission

### File Cleanup
- Files are automatically organized by assignment/user
- Manual deletion available through API
- No automatic cleanup implemented (future enhancement)

## Integration Points

### Frontend Integration
The frontend should:
1. Replace `URL.createObjectURL()` calls with API uploads
2. Store returned `file_id` and `url` in question data
3. Use `/api/assignments/diagrams/{file_id}` for displaying images
4. Handle upload progress and errors

### Database Storage
Question objects store diagram references as:
```json
{
  "diagram": {
    "file_id": "uuid-string",
    "filename": "original_name.png",
    "url": "/api/assignments/diagrams/{file_id}"
  }
}
```

## Error Handling

### Common Error Responses

**400 Bad Request**:
- Invalid file type
- File size exceeds limit
- Missing required parameters

**403 Forbidden**:
- User lacks permission to upload/access/delete
- Assignment access denied

**404 Not Found**:
- Assignment not found
- File not found in storage

**500 Internal Server Error**:
- S3 storage not configured
- Storage operation failed

## Testing

Use the provided test script:

```bash
cd /e:/VidyAI/Dev/vidya_ai_backend
python test_diagram_upload.py
```

**Prerequisites**:
1. Backend server running
2. Valid Firebase token
3. S3 configuration in place

## Configuration Requirements

### Environment Variables
Ensure these are configured in your environment:

```
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_S3_BUCKET=your_bucket_name
AWS_REGION=your_region
```

### Dependencies
The implementation uses existing dependencies:
- `fastapi` - Web framework
- `boto3` - S3 client (via existing config)
- `python-multipart` - File upload handling

## Future Enhancements

1. **File Validation**: More strict image validation
2. **Image Processing**: Resize/optimize uploaded images
3. **Batch Operations**: Upload multiple files at once
4. **File Metadata**: Store additional metadata in database
5. **Cleanup Jobs**: Automated removal of orphaned files
6. **CDN Integration**: Use CloudFront for better performance
7. **Version Control**: Support file versioning

## Security Considerations

1. **File Type Validation**: Only allow safe image/PDF formats
2. **Size Limits**: Prevent large file uploads (10MB limit)
3. **Access Control**: Strict permission checking
4. **Temporary URLs**: Presigned URLs expire after 1 hour
5. **Path Traversal**: UUID-based file names prevent path attacks

## Monitoring

Key metrics to monitor:
- Upload success/failure rates
- File storage usage
- S3 costs
- Response times
- Error rates by endpoint

## Support

For issues or questions:
1. Check server logs for detailed error messages
2. Verify S3 configuration and permissions
3. Test with the provided test script
4. Check Firebase authentication tokens
