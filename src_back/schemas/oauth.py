"""Serialization of sign-in providers and the accounts linked through them."""

from marshmallow import Schema, fields

from src_back.models import OAuthAccount
from src_back.schemas.base import BaseSchema


class OAuthProviderSchema(Schema):
    """Serialize an enabled provider for the sign-in pages; its keys stay out."""

    name = fields.String(dump_only=True)
    label = fields.String(dump_only=True)


class OAuthAccountSchema(BaseSchema):
    """Serialize a link for its owner.

    Every field is dump-only, because linking happens in the provider callback. The
    provider's subject stays out: the client has no use for it.
    """

    class Meta(BaseSchema.Meta):
        """Bind to the ``oauth_accounts`` table and hide the provider's subject."""

        model = OAuthAccount
        exclude = ('provider_user_id',)
        dump_only = (*BaseSchema.AUDIT, 'provider', 'email', 'display_name')


oauth_provider_schema = OAuthProviderSchema()
oauth_account_schema = OAuthAccountSchema()
