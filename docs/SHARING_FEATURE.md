# Shareable Links Feature

This document describes the implementation of shareable links for folders and chat sessions in VidyaAI.

## Overview

The sharing system allows users to:
1. **Share Gallery Folders** - Share entire folders with their videos
2. **Share Chat Sessions** - Share specific chat conversations with videos
3. **Public vs Private Links** - Create public links or invite-only private links
4. **Email-based Invitations** - Search and invite users by email using Firebase Auth
5. **Permission Management** - Manage who has access to shared content

## Architecture

### Backend Components

#### Database Models (`models.py`)
- **SharedLink** - Core sharing model storing link metadata
- **SharedLinkAccess** - User-specific access permissions for private links

#### API Routes (`routes/sharing.py`)
- `POST /api/sharing/search-users` - Search users by email
- `POST /api/sharing/links` - Create new shareable links
- `GET /api/sharing/links` - List user's shared links
- `GET /api/sharing/links/shared-with-me` - List links shared with user
- `PUT /api/sharing/links/{id}` - Update shared link settings
- `DELETE /api/sharing/links/{id}` - Delete shared link
- `POST /api/sharing/links/{id}/users` - Add users to private link
- `DELETE /api/sharing/links/{id}/users` - Remove users from private link
- `GET /api/sharing/public/{token}` - Public access to shared content

#### Firebase Integration (`utils/firebase_users.py`)
- User search by email pattern
- User validation and metadata retrieval
- No additional database tables needed - uses Firebase Auth directly

### Frontend Components

#### Sharing Modal (`components/Sharing/SharingModal.jsx`)
- Create public/private shareable links
- Email-based user search and invitation
- Real-time user search with debouncing
- Copy-to-clipboard functionality

#### Shared Resource Viewer (`components/Sharing/SharedResourceViewer.jsx`)
- Public access to shared folders and chat sessions
- No authentication required for public links
- Responsive design for shared content display

#### Integration Points
- **Gallery Component** - Share buttons for folders
- **Chat Component** - Share buttons for chat sessions
- **App Router** - Handle `/shared/{token}` routes

## Database Schema

### shared_links table
```sql
- id (string, primary key)
- share_token (string, unique, indexed)
- owner_id (string, indexed) -- Firebase UID
- share_type (string) -- 'folder' or 'chat'
- folder_id (string, nullable, foreign key)
- video_id (string, nullable, foreign key)
- chat_session_id (string, nullable)
- is_public (boolean)
- title (string, nullable)
- description (string, nullable)
- expires_at (datetime, nullable)
- max_views (string, nullable)
- view_count (string, default '0')
- created_at (datetime)
- updated_at (datetime)
```

### shared_link_access table
```sql
- id (string, primary key)
- shared_link_id (string, foreign key)
- user_id (string, indexed) -- Firebase UID
- permission (string, default 'view')
- invited_at (datetime)
- accessed_at (datetime, nullable)
- last_accessed_at (datetime, nullable)
```

## Usage Examples

### Creating a Public Folder Share
```javascript
const response = await api.post('/api/sharing/links', {
  share_type: 'folder',
  folder_id: 'folder-uuid',
  is_public: true,
  title: 'My Public Folder',
  description: 'Collection of educational videos'
});
```

### Creating a Private Chat Share
```javascript
const response = await api.post('/api/sharing/links', {
  share_type: 'chat',
  video_id: 'video-uuid',
  chat_session_id: 'session-uuid',
  is_public: false,
  invited_users: ['firebase-uid-1', 'firebase-uid-2']
});
```

### Accessing Shared Content
Public links are accessible at: `https://yourapp.com/shared/{share_token}`

## Security Features

1. **Token-based Access** - Secure random tokens for sharing
2. **Firebase Authentication** - Leverages existing user system
3. **Permission Validation** - Ownership checks for all operations
4. **Expiration Support** - Optional link expiration dates
5. **View Limits** - Optional maximum view counts
6. **Private Link Control** - Invite-only access with user validation

## Migration

Run the database migration to create the sharing tables:
```bash
alembic upgrade head
```

The migration file is located at: `alembic/versions/add_sharing_tables.py`

## Frontend Usage

### Sharing a Folder
1. Navigate to Gallery
2. Hover over a folder
3. Click the share button (Share2 icon)
4. Configure sharing settings in the modal
5. Copy the generated link

### Sharing a Chat Session
1. Open a chat session
2. Click the history button
3. Find the session to share
4. Click the share button next to the session
5. Configure sharing settings and copy link

### Viewing Shared Content
1. Navigate to the shared URL
2. Content displays without authentication for public links
3. Private links require the user to be logged in and invited

## Error Handling

The system handles various error cases:
- Invalid or expired share tokens
- Private links without proper access
- View limit exceeded
- Non-existent resources
- Firebase user validation failures

## Performance Considerations

1. **User Search** - Currently searches all Firebase users; consider implementing search indexing for large user bases
2. **Caching** - Consider caching user data and shared link metadata
3. **Database Indexes** - Proper indexing on share_token, owner_id, and user_id fields
4. **Rate Limiting** - Consider implementing rate limits for sharing operations
