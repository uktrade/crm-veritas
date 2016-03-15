import functools
import flask
import jwt
import os

from datetime import datetime, timedelta

from oic import rndstr
from oic.oic import Client
from oic.utils.authn.client import CLIENT_AUTHN_METHOD
from oic.oic.message import AuthorizationResponse, RegistrationResponse

from werkzeug.utils import redirect

#
# The path the user will take
#
# 1. UI to App server: Initial request
# 2. App server to UI: Rejected: redirect to the auth server
# 3. UI to auth server: "Can I haz auth?"                                      <
# 4. Auth server to UI: "Dunno, ask Micros~1". Redirect to Azure               <
# 5. UI to Azure: Go through the proof process
# 6. Azure to UI: Accepted. Redirect to the auth server
# 7. UI to auth server: "See? I'm legit!"                                      <
# 8. Auth server to UI: Accepted.  Set cookie.  Redirect to app server.        <
# 9. "I haz cookie. Gimmie"
#

SECRET = os.getenv("VERITAS_SECRET", "secret")
COOKIE = "arbiter"

database = {}  # A poor man's database


class Oidc(object):

    CLIENT_ID = "ce058762-5f66-4bbe-85b2-ed617ca4ee9e"
    CLIENT_SECRET = "4D+DTGv1uQLeXlX6JXuQy+9cCecPllqrtc34t+N+Nb4="
    APP_TOKEN = "86be2709-019a-432f-8e59-7057d078dd00"

    ENDPOINT_DOMAIN = "login.microsoftonline.com"
    AUTH_ENDPOINT = "https://{}/{}/oauth2/authorize".format(
        ENDPOINT_DOMAIN, APP_TOKEN)
    TOKEN_ENDPOINT = "https://{}/{}/oauth2/token".format(
        ENDPOINT_DOMAIN, APP_TOKEN)

    REDIRECT_URI = "http://azure.danielquinn.org:5000/oauth2"

    def __init__(self):
        self.callback = None
        self.client = Client(client_authn_method=CLIENT_AUTHN_METHOD)
        self.client.store_registration_info(RegistrationResponse(
            client_secret=self.CLIENT_SECRET,
            client_id=self.CLIENT_ID
        ))

    def _authenticate(self):
        """
        Step 4: Auth server to UI: "Dunno, ask Micros~1". Redirect to Azure
        """
        print("_authenticate")

        if flask.g.get('userinfo', None):
            return self.callback()

        flask.session["eventual-target"] = flask.request.args.get("next")
        flask.session["state"] = str(rndstr())
        flask.session["nonce"] = str(rndstr())
        login_url = self.client.construct_AuthorizationRequest(request_args={
            "client_id": self.client.client_id,
            "response_type": "code",
            "scope": ["openid"],
            "redirect_uri": self.REDIRECT_URI,
            "state": flask.session["state"],
            "nonce": flask.session["nonce"],
        }).request(self.client.authorization_endpoint)

        return redirect("https://{}/{}/oauth2/authorize{}".format(
            self.ENDPOINT_DOMAIN,
            self.APP_TOKEN,
            login_url
        ))

    def auth(self, fn):
        """
        :type fn: function

        Step 3: UI to auth server: "Can I haz auth?"
        """

        self.callback = fn

        @functools.wraps(fn)
        def wrapper():
            return self._authenticate()

        return wrapper


app = flask.Flask(__name__)
oidc = Oidc()


@app.route('/')
@oidc.auth
def index():
    return redirect(flask.session["eventual-target"])


@app.route('/oauth2')
def oauth2():
    """
    This is where Azure drops the user after it's done with them.  It sends
    along a bunch of encoded data, which we decode to verify the redirect.  Then
    we generate a JSON web token (jwt), stuff it into a cookie on the user's
    browser and bounce them back to the app server.
    """

    azure_response = oidc.client.parse_response(
        AuthorizationResponse,
        info=str(flask.request.query_string, "utf-8"),
        sformat="urlencoded"
    )

    if not azure_response["state"] == flask.session["state"]:
        return flask.abort(403)

    now = datetime.utcnow()
    payload = {
        "id": rndstr(),
        "created": now.isoformat(),
        "expires": (now + timedelta(minutes=30)).isoformat()
    }

    database[payload["id"]] = "Daniel"
    response = redirect(flask.session["eventual-target"])
    response.set_cookie(COOKIE, jwt.encode(payload, SECRET))

    return response


if __name__ == '__main__':
    app.secret_key = "secret"
    app.run(debug=True, port=5000)
