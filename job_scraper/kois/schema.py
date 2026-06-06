from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from job_scraper.kois.db import Base


class ReviewStatus(str, enum.Enum):
    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_REVIEW = "needs_review"
    MANUALLY_MERGED = "manually_merged"
    MANUALLY_SPLIT = "manually_split"
    IGNORED = "ignored"
    WATCH_ONLY = "watch_only"


class RawSourceItem(Base):
    __tablename__ = "raw_source_items"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_name",
            "external_id",
            name="uq_raw_source_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_name: Mapped[str] = mapped_column(String(128), index=True)
    external_id: Mapped[str] = mapped_column(String(512), index=True)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_body: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    extracted_records: Mapped[list["ExtractedRecord"]] = relationship(
        back_populates="raw_source", cascade="all, delete-orphan"
    )


class ExtractedRecord(Base):
    __tablename__ = "extracted_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_source_item_id: Mapped[int] = mapped_column(
        ForeignKey("raw_source_items.id"), index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    customer: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    broker: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    raw_source: Mapped[RawSourceItem] = relationship(back_populates="extracted_records")
    cluster_links: Mapped[list["ClusterSource"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class OpportunityCluster(Base):
    __tablename__ = "opportunity_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    customer: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    primary_source_record_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("extracted_records.id"), nullable=True
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.NEEDS_REVIEW, index=True
    )
    confidence: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    sources: Mapped[list["ClusterSource"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    comparisons: Mapped[list["SourceComparison"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    review_history: Mapped[list["ReviewState"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    digest_items: Mapped[list["DigestItem"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class ClusterSource(Base):
    __tablename__ = "cluster_sources"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_cluster_id",
            "extracted_record_id",
            name="uq_cluster_source_record",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_cluster_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_clusters.id"), index=True
    )
    extracted_record_id: Mapped[int] = mapped_column(
        ForeignKey("extracted_records.id"), index=True
    )
    match_confidence: Mapped[float] = mapped_column(default=0.0)
    match_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cluster: Mapped[OpportunityCluster] = relationship(back_populates="sources")
    record: Mapped[ExtractedRecord] = relationship(back_populates="cluster_links")


class SourceComparison(Base):
    __tablename__ = "source_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_cluster_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_clusters.id"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(128))
    values_json: Mapped[dict] = mapped_column("values", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    cluster: Mapped[OpportunityCluster] = relationship(back_populates="comparisons")


class ReviewState(Base):
    __tablename__ = "review_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_cluster_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_clusters.id"), index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    cluster: Mapped[OpportunityCluster] = relationship(back_populates="review_history")


class DigestItem(Base):
    __tablename__ = "digest_items"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_cluster_id",
            "review_status",
            name="uq_digest_cluster_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_cluster_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_clusters.id"), index=True
    )
    review_status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), index=True)
    payload_json: Mapped[dict] = mapped_column("payload", JSON, default=dict)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cluster: Mapped[OpportunityCluster] = relationship(back_populates="digest_items")
