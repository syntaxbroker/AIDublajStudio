from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactLink


class ArtifactRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, artifact: Artifact) -> Artifact:
        self.db.add(artifact)
        return artifact

    def create_link(self, link: ArtifactLink) -> ArtifactLink:
        self.db.add(link)
        return link

    def list_for_project(self, project_id: str) -> list[Artifact]:
        stmt = select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc())
        return list(self.db.scalars(stmt))

    def get_by_id(self, artifact_id: str) -> Artifact | None:
        return self.db.get(Artifact, artifact_id)

    def get_by_checksum(self, project_id: str, artifact_type: str, checksum_sha256: str) -> Artifact | None:
        stmt = select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.artifact_type == artifact_type,
            Artifact.checksum_sha256 == checksum_sha256,
        )
        return self.db.scalar(stmt)

    def list_links_for_project(self, project_id: str) -> list[ArtifactLink]:
        stmt = (
            select(ArtifactLink)
            .join(Artifact, Artifact.id == ArtifactLink.child_artifact_id)
            .where(Artifact.project_id == project_id)
        )
        return list(self.db.scalars(stmt))
