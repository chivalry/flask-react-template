"""Serialization of passkeys, and validation of the ceremony and rename payloads."""

from typing import Any

from marshmallow import Schema, fields, pre_load, validate

from src_back.models import WebAuthnCredential
from src_back.schemas.base import BaseSchema

NICKNAME_RULE = validate.Length(max=64, error='Use 64 characters or fewer.')


class PasskeySchema(BaseSchema):
    """Serialize a passkey for its owner.

    Every field is dump-only: the registration ceremony creates a passkey, and only its
    nickname changes after, through :class:`PasskeyRenameSchema`. The credential id, the
    public key, and the counter stay out, since the client has no use for them, and an
    auto schema leaves out ``user_id``.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``webauthn_credentials`` table and hide the key material."""

        model = WebAuthnCredential
        exclude = ('credential_id', 'public_key', 'sign_count')
        dump_only = (
            *BaseSchema.AUDIT,
            'nickname',
            'transports',
            'aaguid',
            'backup_eligible',
            'backup_state',
            'last_used_at',
        )


class _NicknameSchema(Schema):
    """Trim a payload's nickname before its length rule runs; a blank one becomes null."""

    @pre_load
    def _trim_nickname(self, data: object, **_kwargs: Any) -> object:
        """Trim the nickname, so a padded name of the maximum length still passes.

        Args:
            data: The payload as the client sent it.
            **_kwargs: What marshmallow passes every hook, such as ``many``. Unused.

        Returns:
            The payload with its nickname trimmed, or ``None`` when the trim leaves
            nothing; any other payload unchanged, for validation to refuse.
        """
        if isinstance(data, dict) and isinstance(data.get('nickname'), str):
            return {**data, 'nickname': data['nickname'].strip() or None}
        return data


class PasskeyRegisterSchema(_NicknameSchema):
    """Validate the answer to the registration options, with an optional nickname."""

    credential = fields.Dict(required=True)
    nickname = fields.String(load_default=None, allow_none=True, validate=NICKNAME_RULE)


class PasskeyAssertionSchema(Schema):
    """Validate the answer to the sign-in options."""

    credential = fields.Dict(required=True)


class PasskeyRenameSchema(_NicknameSchema):
    """Validate a passkey's new nickname; null or a blank one clears it."""

    nickname = fields.String(required=True, allow_none=True, validate=NICKNAME_RULE)


passkey_schema = PasskeySchema()
passkey_register_schema = PasskeyRegisterSchema()
passkey_assertion_schema = PasskeyAssertionSchema()
passkey_rename_schema = PasskeyRenameSchema()
