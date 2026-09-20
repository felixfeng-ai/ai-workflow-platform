"""add deploy runs

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """远程部署：项目上加 workflow 文件名 + 新建部署记录表。

    projects.deploy_workflow 为 NULL 表示该项目不可远程部署（前端只显示「线上」外链）。
    现有数据全部落在 NULL 上，语义正确 —— 老项目本来就没配过 workflow。
    """
    op.add_column(
        'projects',
        sa.Column('deploy_workflow', sa.String(length=120), nullable=True),
    )
    op.create_table(
        'deploy_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('workflow', sa.String(length=120), nullable=False),
        sa.Column('repo_full_name', sa.String(length=200), nullable=False),
        sa.Column('github_run_id', sa.String(length=40), nullable=True),
        sa.Column('run_url', sa.String(length=400), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_deploy_runs_tenant_id'), 'deploy_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_deploy_runs_project_id'), 'deploy_runs', ['project_id'], unique=False)
    op.create_index(op.f('ix_deploy_runs_user_id'), 'deploy_runs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_deploy_runs_user_id'), table_name='deploy_runs')
    op.drop_index(op.f('ix_deploy_runs_project_id'), table_name='deploy_runs')
    op.drop_index(op.f('ix_deploy_runs_tenant_id'), table_name='deploy_runs')
    op.drop_table('deploy_runs')
    op.drop_column('projects', 'deploy_workflow')
