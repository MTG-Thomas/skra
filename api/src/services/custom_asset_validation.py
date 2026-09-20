"""
Custom Asset Validation Service.

Provides validation, encryption, and filtering functions for custom asset values.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.core.security import decrypt_secret, encrypt_secret
from src.models.contracts.custom_asset import FieldDefinition


class CustomAssetValidationError(ValueError):
    """Exception raised when custom asset validation fails."""

    def __init__(self, message: str, field_key: str | None = None):
        self.field_key = field_key
        super().__init__(message)


def validate_field_definitions(fields: list[FieldDefinition]) -> None:
    """
    Validate field definitions for a custom asset type.

    Args:
        fields: List of field definitions to validate

    Raises:
        CustomAssetValidationError: If validation fails
    """
    keys = [f.key for f in fields]
    if len(keys) != len(set(keys)):
        raise CustomAssetValidationError("Field keys must be unique within a custom asset type")

    for field in fields:
        # Validate select type has options
        if field.type == "select" and (not field.options or len(field.options) == 0):
            raise CustomAssetValidationError(
                f"Select field '{field.key}' requires options",
                field_key=field.key,
            )
        # Validate checklist type has items (mirrors the contract validator
        # so service-level callers get the same guarantee)
        if field.type == "checklist":
            items = field.checklist_items or []
            if len(items) == 0:
                raise CustomAssetValidationError(
                    f"Checklist field '{field.key}' requires at least one item",
                    field_key=field.key,
                )
            labels = [item.label.strip() for item in items]
            if any(not label for label in labels):
                raise CustomAssetValidationError(
                    f"Checklist field '{field.key}' items must have non-empty labels",
                    field_key=field.key,
                )
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise CustomAssetValidationError(
                    f"Checklist field '{field.key}' item ids must be unique",
                    field_key=field.key,
                )


def validate_values(
    type_fields: list[FieldDefinition],
    values: dict[str, Any],
    partial: bool = False,
) -> None:
    """
    Validate values against a custom asset type's field definitions.

    Args:
        type_fields: List of field definitions from the custom asset type
        values: Dictionary of values to validate
        partial: If True, skip required field validation (for updates)

    Raises:
        CustomAssetValidationError: If validation fails
    """
    field_map = {f.key: f for f in type_fields}
    valid_keys = set(field_map.keys())

    # Check for unknown keys
    provided_keys = set(values.keys())
    unknown_keys = provided_keys - valid_keys
    if unknown_keys:
        raise CustomAssetValidationError(f"Unknown field keys: {', '.join(sorted(unknown_keys))}")

    # Validate each provided value
    for key, value in values.items():
        field = field_map[key]
        _validate_field_value(field, value)

    # Check required fields (skip headers which are display-only)
    if not partial:
        for field in type_fields:
            if field.required and field.type != "header":
                if field.key not in values or values[field.key] is None:
                    raise CustomAssetValidationError(
                        f"Required field '{field.key}' is missing",
                        field_key=field.key,
                    )


def _validate_field_value(field: FieldDefinition, value: Any) -> None:
    """
    Validate a single field value against its definition.

    Args:
        field: Field definition
        value: Value to validate

    Raises:
        CustomAssetValidationError: If validation fails
    """
    # Allow None for optional fields
    if value is None:
        if field.required and field.type != "header":
            raise CustomAssetValidationError(
                f"Required field '{field.key}' cannot be null",
                field_key=field.key,
            )
        return

    # Type-specific validation
    match field.type:
        case "text" | "textbox" | "password" | "totp":
            if not isinstance(value, str):
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a string",
                    field_key=field.key,
                )
        case "number":
            if not isinstance(value, (int, float)):
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a number",
                    field_key=field.key,
                )
        case "date":
            if not isinstance(value, str):
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a date string",
                    field_key=field.key,
                )
            # Try to parse the date
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as e:
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a valid ISO date string: {e}",
                    field_key=field.key,
                ) from e
        case "checkbox":
            if not isinstance(value, bool):
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a boolean",
                    field_key=field.key,
                )
        case "select":
            if not isinstance(value, str):
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be a string",
                    field_key=field.key,
                )
            if field.options and value not in field.options:
                raise CustomAssetValidationError(
                    f"Field '{field.key}' must be one of: {', '.join(field.options)}",
                    field_key=field.key,
                )
        case "header":
            # Headers don't have values
            pass
        case "checklist":
            _validate_checklist_value(field, value)


def _validate_checklist_value(field: FieldDefinition, value: Any) -> None:
    """
    Validate a checklist value's shape against its item definitions.

    The value must be a dict with an "items" list; every entry needs a known
    item id and a boolean "completed". Client-supplied completion stamps are
    ignored here (the server owns them in merge_checklist_value).

    Args:
        field: Field definition (must carry checklist_items)
        value: Value to validate

    Raises:
        CustomAssetValidationError: If validation fails
    """
    if not isinstance(value, dict):
        raise CustomAssetValidationError(
            f"Field '{field.key}' must be an object with an items list",
            field_key=field.key,
        )
    items = value.get("items", [])
    if not isinstance(items, list):
        raise CustomAssetValidationError(
            f"Field '{field.key}' items must be a list",
            field_key=field.key,
        )
    known_ids = {item.id for item in field.checklist_items or []}
    for entry in items:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise CustomAssetValidationError(
                f"Field '{field.key}' entries must have a string id",
                field_key=field.key,
            )
        if entry["id"] not in known_ids:
            raise CustomAssetValidationError(
                f"Field '{field.key}' has unknown checklist item '{entry['id']}'",
                field_key=field.key,
            )
        if not isinstance(entry.get("completed"), bool):
            raise CustomAssetValidationError(
                f"Checklist item '{entry['id']}' must have a boolean completed flag",
                field_key=field.key,
            )


def merge_checklist_value(
    field: FieldDefinition,
    stored_value: Any | None,
    incoming_value: Any | None,
    completed_by_user_id: UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Merge an incoming checklist state into the stored one at item granularity.

    Items absent from the incoming list keep their stored state, so concurrent
    writers toggling different items do not overwrite each other (provided the
    caller serializes writers, e.g. via a row lock). Completion stamps are
    server-owned: newly completed items are stamped with the acting user and
    server time, persisting stamps are kept, uncompleted items lose stamps,
    and any client-supplied stamps are ignored. Stored entries for items since
    removed from the definition are preserved untouched so completion history
    survives definition edits.

    Args:
        field: Field definition with checklist_items
        stored_value: Previously stored value (dict with items list) or None
        incoming_value: Incoming value (dict with items list) or None
        completed_by_user_id: Acting user stamped on newly completed items
        now: Timestamp for new stamps (defaults to current UTC time)

    Returns:
        Merged checklist value in storage shape
    """
    now = now or datetime.now(UTC)
    timestamp = now.isoformat()

    stored_items: dict[str, dict[str, Any]] = {}
    if isinstance(stored_value, dict):
        raw_items = stored_value.get("items", [])
        if isinstance(raw_items, list):
            for entry in raw_items:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    stored_items[entry["id"]] = entry

    incoming_items: dict[str, bool] = {}
    if isinstance(incoming_value, dict):
        raw_items = incoming_value.get("items", [])
        if isinstance(raw_items, list):
            for entry in raw_items:
                if isinstance(entry, dict) and isinstance(entry.get("completed"), bool):
                    incoming_items[entry["id"]] = entry["completed"]

    merged: dict[str, dict[str, Any]] = {}
    for item_id, completed in incoming_items.items():
        prior = stored_items.get(item_id, {})
        if completed and not prior.get("completed"):
            merged[item_id] = {
                "id": item_id,
                "completed": True,
                "completed_by": str(completed_by_user_id),
                "completed_at": timestamp,
            }
        elif completed:
            merged[item_id] = {
                "id": item_id,
                "completed": True,
                "completed_by": prior.get("completed_by"),
                "completed_at": prior.get("completed_at"),
            }
        else:
            merged[item_id] = {"id": item_id, "completed": False}

    # Preserve stored entries the incoming list does not mention (unchanged
    # items, plus history for items since removed from the definition).
    for item_id, prior in stored_items.items():
        if item_id not in merged:
            merged[item_id] = dict(prior)

    return {"items": list(merged.values())}


def initialize_checklist_values(
    type_fields: list[FieldDefinition],
    values: dict[str, Any],
) -> dict[str, Any]:
    """
    Ensure every checklist field has a value entry (initially all incomplete).

    Checklist fields are completed interactively after creation, so a missing
    key is initialized rather than treated as absent.

    Args:
        type_fields: List of field definitions from the custom asset type
        values: Dictionary of provided values

    Returns:
        Values dictionary with empty checklist states for missing fields
    """
    result = values.copy()

    for field in type_fields:
        if field.type == "checklist" and field.key not in result:
            result[field.key] = {"items": []}

    return result


def values_key_to_id(
    type_fields: list[FieldDefinition],
    values: dict[str, Any],
) -> dict[str, Any]:
    """
    Transform values from key-based (API format) to ID-based (storage format).

    Also encrypts password/totp fields.

    Args:
        type_fields: List of field definitions from the custom asset type
        values: Dictionary of values keyed by field key

    Returns:
        Values dictionary keyed by field ID, with password/totp fields encrypted
    """
    key_to_field = {f.key: f for f in type_fields}
    result: dict[str, Any] = {}

    for key, value in values.items():
        field = key_to_field.get(key)
        if not field:
            # Unknown key - skip (validation should have caught this)
            continue

        if value is not None and field.type in ("password", "totp"):
            # Encrypt sensitive fields
            result[field.id] = encrypt_secret(str(value))
        else:
            result[field.id] = value

    return result


def values_id_to_key(
    type_fields: list[FieldDefinition],
    values: dict[str, Any],
    *,
    decrypt_secrets: bool = False,
    filter_secrets: bool = False,
) -> dict[str, Any]:
    """
    Transform values from ID-based (storage format) to key-based (API format).

    Args:
        type_fields: List of field definitions from the custom asset type
        values: Dictionary of values keyed by field ID
        decrypt_secrets: If True, decrypt password/totp fields
        filter_secrets: If True, exclude password/totp fields from result

    Returns:
        Values dictionary keyed by field key
    """
    id_to_field = {f.id: f for f in type_fields}
    result: dict[str, Any] = {}

    for field_id, value in values.items():
        field = id_to_field.get(field_id)
        if not field:
            # Unknown field ID - could be from old/removed field, skip
            continue

        if field.type in ("password", "totp"):
            if filter_secrets:
                # Don't include in result
                continue
            elif decrypt_secrets and value is not None:
                # Decrypt for reveal endpoint
                result[field.key] = decrypt_secret(value)
            else:
                # Include encrypted value as-is (shouldn't normally happen)
                result[field.key] = value
        else:
            result[field.key] = value

    return result


def apply_default_values(
    type_fields: list[FieldDefinition],
    values: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply default values for fields not provided.

    Args:
        type_fields: List of field definitions from the custom asset type
        values: Dictionary of provided values

    Returns:
        Values dictionary with defaults applied for missing fields
    """
    result = values.copy()

    for field in type_fields:
        if field.key not in result and field.default_value is not None:
            # Convert default value to appropriate type
            match field.type:
                case "checkbox":
                    result[field.key] = field.default_value.lower() == "true"
                case "number":
                    try:
                        result[field.key] = float(field.default_value)
                    except ValueError:
                        result[field.key] = field.default_value
                case _:
                    result[field.key] = field.default_value

    return result
