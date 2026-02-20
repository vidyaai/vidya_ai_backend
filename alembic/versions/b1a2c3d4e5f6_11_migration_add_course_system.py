"""11 migration Add course organization system

Revision ID: b1a2c3d4e5f6
Revises: 988d09ba0571
Create Date: 2026-02-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1a2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "988d09ba0571"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create courses, course_enrollments, course_materials tables and add course_id to assignments."""

    # 1. courses table
    op.create_table(
        "courses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("course_code", sa.String(), nullable=True),
        sa.Column("semester", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("enrollment_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_code"),
    )
    op.create_index(op.f("ix_courses_user_id"), "courses", ["user_id"], unique=False)

    # 2. course_enrollments table
    op.create_table(
        "course_enrollments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True, server_default="student"),
        sa.Column("status", sa.String(), nullable=True, server_default="active"),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_course_enrollments_course_id"),
        "course_enrollments",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_course_enrollments_user_id"),
        "course_enrollments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_course_enrollments_email"),
        "course_enrollments",
        ["email"],
        unique=False,
    )

    # 3. course_materials table
    op.create_table(
        "course_materials",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "material_type", sa.String(), nullable=True, server_default="lecture_notes"
        ),
        sa.Column("s3_key", sa.String(), nullable=True),
        sa.Column("video_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_size", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("folder", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_course_materials_course_id"),
        "course_materials",
        ["course_id"],
        unique=False,
    )

    # 4. Add nullable course_id to assignments
    op.add_column("assignments", sa.Column("course_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_assignments_course_id",
        "assignments",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_assignments_course_id"),
        "assignments",
        ["course_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove course system tables and column."""
    op.drop_index(op.f("ix_assignments_course_id"), table_name="assignments")
    op.drop_constraint("fk_assignments_course_id", "assignments", type_="foreignkey")
    op.drop_column("assignments", "course_id")

    op.drop_index(op.f("ix_course_materials_course_id"), table_name="course_materials")
    op.drop_table("course_materials")

    op.drop_index(
        op.f("ix_course_enrollments_email"), table_name="course_enrollments"
    )
    op.drop_index(
        op.f("ix_course_enrollments_user_id"), table_name="course_enrollments"
    )
    op.drop_index(
        op.f("ix_course_enrollments_course_id"), table_name="course_enrollments"
    )
    op.drop_table("course_enrollments")

    op.drop_index(op.f("ix_courses_user_id"), table_name="courses")
    op.drop_table("courses")
