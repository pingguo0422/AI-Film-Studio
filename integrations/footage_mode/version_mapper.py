"""Immutable package and run provenance snapshots."""
from .adapter import PackageDescriptor

def package_snapshot(descriptor: PackageDescriptor) -> dict:
    return {
        "name": descriptor.name,
        "version": descriptor.version,
        "release_status": descriptor.release_status,
        "archive_sha256": descriptor.archive_sha256,
        "member_count": descriptor.member_count,
    }
