"""Offline determinism checks for attachment reconciliation inputs."""

from pathlib import Path

from itglue_migrate.attachments import AttachmentScanner, validate_attachments


def test_attachment_inventory_and_orphans_are_stable(tmp_path: Path) -> None:
    for entity_type in ("passwords", "configurations"):
        for entity_id in ("9", "2"):
            folder = tmp_path / "attachments" / entity_type / entity_id
            folder.mkdir(parents=True)
            (folder / "fixture.txt").write_text("synthetic", encoding="utf-8")

    inventory = AttachmentScanner().get_all_attachments(tmp_path)
    assert list(inventory) == [
        ("configurations", "2"),
        ("configurations", "9"),
        ("passwords", "2"),
        ("passwords", "9"),
    ]
    validation = validate_attachments(tmp_path, {"configurations": set(), "passwords": set()})
    assert validation.orphaned == {"configurations": ["2", "9"], "passwords": ["2", "9"]}


def test_prefixed_floor_plan_inventory_is_stable(tmp_path: Path) -> None:
    for entity_type in ("switches", "routers"):
        folder = tmp_path / f"{entity_type}-floor-plans-photos"
        folder.mkdir()
        for filename in ("9-z.png", "2-b.png", "2-a.png"):
            (folder / filename).write_bytes(b"synthetic")

    inventory = AttachmentScanner().get_all_attachments(tmp_path)
    assert list(inventory) == [
        ("routers_floor_plans_photos", "2"),
        ("routers_floor_plans_photos", "9"),
        ("switches_floor_plans_photos", "2"),
        ("switches_floor_plans_photos", "9"),
    ]
    assert [p.name for p in inventory[("routers_floor_plans_photos", "2")]] == [
        "2-a.png",
        "2-b.png",
    ]
