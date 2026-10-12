"""Persist the ten-second question preview deadline.

The original revision creates tables from current metadata. Inspecting the column
also lets a fresh database pass this revision after 0001 creates the new schema.
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_question_preview'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('session_questions')}
    if 'preview_ends_at' not in columns:
        op.add_column('session_questions', sa.Column('preview_ends_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('session_questions')}
    if 'preview_ends_at' in columns:
        op.drop_column('session_questions', 'preview_ends_at')
