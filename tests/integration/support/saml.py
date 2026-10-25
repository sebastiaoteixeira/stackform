"""A live SAML identity provider: metadata over HTTP and signed responses to the AuthnRequests it receives."""

import base64
import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onelogin.saml2.utils import OneLogin_Saml2_Utils

_PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
_ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"


def _instant(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _values(values: str | list[str]) -> list[str]:
    return values if isinstance(values, list) else [values]


def _self_signed(key: rsa.RSAPrivateKey) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "saml-idp.test")])
    now = datetime.datetime.now(datetime.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )


@dataclass(frozen=True)
class AuthnRequest:
    id: str
    acs_url: str
    sp_entity_id: str

    @classmethod
    def decode(cls, encoded: str) -> "AuthnRequest":
        root = ElementTree.fromstring(OneLogin_Saml2_Utils.decode_base64_and_inflate(encoded))
        return cls(root.attrib["ID"], root.attrib["AssertionConsumerServiceURL"], root.findtext(f"{{{_ASSERTION}}}Issuer"))


Attributes = dict[str, str | list[str]]


@dataclass(frozen=True)
class Subject:
    name_id: str
    attributes: Attributes


@dataclass
class IdentityProvider:
    url: str
    key: rsa.RSAPrivateKey
    certificate: x509.Certificate
    subject: Subject

    @contextmanager
    def asserting(self, attributes: Attributes) -> Iterator["IdentityProvider"]:
        """Assert ``attributes`` over the current ones until the context exits."""
        current = self.subject
        self.subject = replace(current, attributes={**current.attributes, **attributes})
        try:
            yield self
        finally:
            self.subject = current

    @property
    def metadata_url(self) -> str:
        return f"{self.url}/metadata"

    @property
    def sso_url(self) -> str:
        return f"{self.url}/sso"

    def metadata(self) -> str:
        der = base64.b64encode(self.certificate.public_bytes(serialization.Encoding.DER)).decode()
        return f"""<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="{self.metadata_url}">
  <md:IDPSSODescriptor protocolSupportEnumeration="{_PROTOCOL}">
    <md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data><ds:X509Certificate>{der}</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{self.sso_url}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""

    def response(self, request: AuthnRequest, in_response_to: str | None = None) -> str:
        """Base64 signed Response asserting the current subject to the requesting SP; a list attribute is multi-valued.

        The response answers ``request`` unless ``in_response_to`` names another request, or ``""`` none at all.
        """
        answered = request.id if in_response_to is None else in_response_to
        answering = f' InResponseTo="{escape(answered)}"' if answered else ""
        now = datetime.datetime.now(datetime.UTC)
        issued, expires = _instant(now), _instant(now + datetime.timedelta(minutes=5))
        attributes = "".join(
            f'<saml:Attribute Name="{escape(name)}">'
            + "".join(f"<saml:AttributeValue>{escape(value)}</saml:AttributeValue>" for value in _values(values))
            + "</saml:Attribute>"
            for name, values in self.subject.attributes.items()
        )
        document = f"""<samlp:Response xmlns:samlp="{_PROTOCOL}" xmlns:saml="{_ASSERTION}" ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{issued}" Destination="{escape(request.acs_url)}"{answering}>
  <saml:Issuer>{self.metadata_url}</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  <saml:Assertion ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{issued}">
    <saml:Issuer>{self.metadata_url}</saml:Issuer>
    <saml:Subject>
      <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{escape(self.subject.name_id)}</saml:NameID>
      <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
        <saml:SubjectConfirmationData NotOnOrAfter="{expires}" Recipient="{escape(request.acs_url)}"{answering}/>
      </saml:SubjectConfirmation>
    </saml:Subject>
    <saml:Conditions NotBefore="{issued}" NotOnOrAfter="{expires}">
      <saml:AudienceRestriction><saml:Audience>{escape(request.sp_entity_id)}</saml:Audience></saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AuthnStatement AuthnInstant="{issued}" SessionIndex="_{uuid.uuid4().hex}">
      <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext>
    </saml:AuthnStatement>
    <saml:AttributeStatement>{attributes}</saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>"""
        key = self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        certificate = self.certificate.public_bytes(serialization.Encoding.PEM)
        return base64.b64encode(OneLogin_Saml2_Utils.add_sign(document, key, certificate)).decode()


class _IdentityProviderHandler(BaseHTTPRequestHandler):
    """Serves the metadata, and answers ``/sso`` with the auto-post form a browser would submit to the SP."""

    def __init__(self, provider: IdentityProvider, *args) -> None:
        self.provider = provider
        super().__init__(*args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/metadata":
            self._send("application/samlmetadata+xml", self.provider.metadata())
        elif parsed.path == "/sso":
            request = AuthnRequest.decode(parse_qs(parsed.query)["SAMLRequest"][0])
            self._send(
                "text/html",
                f'<form method="post" action="{escape(request.acs_url)}">'
                f'<input type="hidden" name="SAMLResponse" value="{self.provider.response(request)}"/></form>',
            )
        else:
            self.send_error(404)

    def _send(self, content_type: str, text: str) -> None:
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def live_identity_provider(name_id: str, attributes: Attributes) -> Iterator[IdentityProvider]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *args: _IdentityProviderHandler(provider, *args))
    host, port = server.server_address
    provider = IdentityProvider(f"http://{host}:{port}", key, _self_signed(key), Subject(name_id, attributes))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield provider
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
