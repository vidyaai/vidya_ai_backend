# Sharing Format Fix - Implementation Summary

## Problem
Previously, when assignments were shared with students via PDF or Google Forms format, the student portal would always show the HTML form instead of respecting the selected sharing format.

## Solution
The sharing format (html_form, pdf, or google_forms) is now properly stored in the database and passed to students, who will see the appropriate format when accessing shared assignments.

## Changes Made

### Backend Changes

#### 1. Database Schema (`models.py`)
Added two new columns to the `SharedLink` model:
- `share_format`: String column to store the format type ('html_form', 'pdf', or 'google_forms')
- `google_resource_url`: String column to store the Google Form URL when applicable

#### 2. API Schemas (`schemas.py`)
Updated request/response models:
- **ShareAssignmentRequest**: Added `share_format` field (default: 'html_form')
- **SharedAssignmentOut**: Added `share_format` and `google_resource_url` fields

#### 3. API Endpoints (`routes/assignments.py`)
Updated the following endpoints to handle share_format:

- **POST `/api/assignments/{assignment_id}/share`**: 
  - Now saves the share_format when creating/updating shared links
  - Automatically generates Google Form URL if share_format is 'google_forms'
  
- **PUT `/api/assignments/{assignment_id}/share/{share_id}`**:
  - Updates share_format
  - Generates Google Form if needed and not already created
  
- **GET `/api/assignments/shared-with-me`**:
  - Returns share_format and google_resource_url to students
  
- **GET `/api/assignments/{assignment_id}/share`**:
  - Returns share_format and google_resource_url when retrieving shared link info

#### 4. Database Migration
Created Alembic migration: `add_share_format_to_shared_links.py`
- Adds `share_format` column with default value 'html_form'
- Adds `google_resource_url` column (nullable)

### Frontend Changes

#### 1. DoAssignmentModal Component
Added logic to check the share_format before rendering:

- **PDF Format**: Shows a redirect screen with a "Download PDF" button that links to the PDF download endpoint
- **Google Forms Format**: Shows a redirect screen with an "Open Google Form" button that links to the Google Form URL
- **HTML Form Format**: Shows the standard interactive assignment form (existing behavior)

The component now reads `assignment.share_format` and `assignment.google_resource_url` from the shared assignment data and renders accordingly.

## Flow

### Teacher Sharing Flow
1. Teacher creates an assignment
2. Teacher opens the sharing modal
3. Teacher selects share format (HTML Form, PDF, or Google Forms)
4. Teacher adds students by email
5. Backend creates/updates SharedLink with the selected share_format
6. If Google Forms is selected, backend generates the Google Form and stores the URL

### Student Viewing Flow
1. Student navigates to "Assigned to Me"
2. Student clicks "Do Assignment" on a shared assignment
3. DoAssignmentModal receives the assignment with share_format and google_resource_url
4. Based on share_format:
   - **html_form**: Shows interactive form
   - **pdf**: Shows redirect with PDF download button
   - **google_forms**: Shows redirect with Google Form link

## Migration Instructions

To apply the database changes:

1. Ensure your database is backed up
2. Run the migration:
   ```bash
   cd vidya_ai_backend
   source venv/bin/activate
   alembic upgrade head
   ```

The migration will:
- Add the `share_format` column with default value 'html_form' to all existing shared links
- Add the `google_resource_url` column (nullable)

## Testing

### Test Scenarios
1. **Share as HTML Form**: Student should see the interactive form
2. **Share as PDF**: Student should see a redirect with download button
3. **Share as Google Forms**: Student should see a redirect with Google Form link
4. **Existing Shared Links**: Should default to 'html_form' after migration
5. **Update Format**: Teacher should be able to change format after sharing

### Backward Compatibility
- Existing shared assignments will default to 'html_form' format
- No breaking changes to existing functionality
- All existing HTML form submissions continue to work

## Files Modified

### Backend
- `src/models.py` - Added columns to SharedLink model
- `src/schemas.py` - Updated ShareAssignmentRequest and SharedAssignmentOut schemas
- `src/routes/assignments.py` - Updated sharing endpoints
- `alembic/versions/add_share_format_to_shared_links.py` - New migration file

### Frontend
- `src/components/Assignments/DoAssignmentModal.jsx` - Added format detection and redirect logic

## Future Improvements
- Add analytics to track which format students prefer
- Support multiple formats simultaneously (e.g., provide both PDF and HTML options)
- Add format preview in sharing modal
- Support format-specific settings (e.g., PDF template selection)
