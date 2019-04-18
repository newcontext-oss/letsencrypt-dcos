import os
import stat
import sys
import subprocess
import json
import requests
import time
import operator
from pathlib import Path

ENV_MARATHON_APP_ID = "MARATHON_APP_ID"
ENV_MARATHON_URL = "MARATHON_URL"
DEFAULT_MARATHON_URL = "https://marathon.mesos:8443/"
ENV_LETSENCRYPT_SERVER_URL = "LETSENCRYPT_SERVER_URL"
ENV_LETSENCRYPT_EMAIL = "LETSENCRYPT_EMAIL"
ENV_VERIFICATION_METHOD = "LETSENCRYPT_VERIFICATION_METHOD"
ENV_MARATHON_LB_CERT = os.environ.get('MARATHON_LB_CERT_ENV', 'HAPROXY_SSL_CERT')
ENV_MARATHON_LB_ID = "MARATHON_LB_ID"
ENV_DOMAINS = "DOMAINS"
ENV_DNS_PROVIDER = "DNS_PROVIDER"
DEFAULT_LETSENCRYPT_URL = "https://acme-staging-v02.api.letsencrypt.org/directory"
ENV_RSA_KEY_SIZE = "RSA_KEY_SIZE"
DEFAULT_GCE_CREDENTIALS = "/certbot/google_service_account.json"
ENV_GOOGLE_CREDENTIALS = "GOOGLE_APPLICATION_CREDENTIALS"
ENV_DNS_PROPAGATION_TIMEOUT = "DNS_PROPAGATION_TIMEOUT"
ENV_GCE_SERVICE_ACCOUNT = "GCE_SERVICE_ACCOUNT"

CERTIFICATES_DIR = "/etc/letsencrypt/live"
DOMAINS_FILE = "/etc/letsencrypt/current_domains"

DEFAULT_CERTBOT_ARGS = [
    "certbot",
    "certonly",
    "--server", os.environ.get(ENV_LETSENCRYPT_SERVER_URL, DEFAULT_LETSENCRYPT_URL),
    "--email", os.environ.get(ENV_LETSENCRYPT_EMAIL),
    "--agree-tos",
    "--noninteractive",
    "--rsa-key-size", os.environ.get(ENV_RSA_KEY_SIZE, "4096"),
    "--expand"
]

CERTBOT_ARGS_HTTP = [
    "--standalone",
    "--no-redirect",
    "--preferred-challenges",
    "http-01"
]

CERTBOT_ARGS_DNS = [
    "--preferred-challenges",
    "dns-01"
]

CERTBOT_ARGS_DNS_GCLOUD = [
    "--dns-google",
    "--dns-google-credentials", os.environ.get(ENV_GOOGLE_CREDENTIALS, DEFAULT_GCE_CREDENTIALS),
    "--dns-google-propagation-seconds", os.environ.get(ENV_DNS_PROPAGATION_TIMEOUT, "120")
]

CERTBOT_ARGS_DNS_ROUTE53 = [
    "--dns-route53",
    "--dns-route53-propagation-seconds", os.environ.get(ENV_DNS_PROPAGATION_TIMEOUT, "120")
]


def get_marathon_url():
    """Retrieves the marathon base url to use from an environment variable"""
    return os.environ.get(ENV_MARATHON_URL, DEFAULT_MARATHON_URL)


def get_letsencrypt_url():
    """Retrieves the LetsEncrypt Server URL"""
    return os.environ.get(ENV_LETSENCRYPT_SERVER_URL, DEFAULT_LETSENCRYPT_URL)


def get_marathon_app(app_id):
    """Retrieve app definition for marathon-lb app"""
    response = requests.get(f"{get_marathon_url()}/v2/apps/{app_id}", verify=False)
    if not response.ok:
        raise Exception("Could not get app details from marathon")
    return response.json()


def read_domains_from_last_time():
    """Return list of domains used (last time this script was run) from file or empty string if file does not exist"""
    if os.path.exists(DOMAINS_FILE):
        with open(DOMAINS_FILE) as domains_file:
            return domains_file.read()
    else:
        return ""


def write_domains_to_file(domains):
    """Store list of domains in file to retrieve on next run"""
    with open(DOMAINS_FILE, "w+") as domains_file:
        domains_file.write(domains)


def rewrite_domain_name(domain_name):
    """Rewrite domain_name if it is a wildcard"""
    if domain_name.startswith("*"):
        domain_name = domain_name.replace("*.", "")
    return domain_name


def find_newest_dir(domain_name):
    dirs = {}
    # Check if the certificate has been recreated with a new domain list
    for x in os.listdir(CERTIFICATES_DIR):
        if x.startswith(domain_name):
            # Dict all the directories and their creation times in the CERTIFICATES_DIR that start with the domain_name
            xpath = f"{CERTIFICATES_DIR}/{x}"
            dirs[xpath] = os.path.getctime(xpath)
    # Return the newest directory in the dict
    list_dir = sorted(dirs.items(), key=operator.itemgetter(1))
    return list_dir[-1][0]


def write_combined_cert_to_file(domain_name):
    """Create the combined cert from the full chain and private key files"""
    domain_name = rewrite_domain_name(domain_name)
    latest_cert_dir = find_newest_dir(domain_name)

    Path(f"{latest_cert_dir}/{domain_name}.pem").write_text(Path(f"{latest_cert_dir}/fullchain.pem").read_text() +
        Path(f"{latest_cert_dir}/privkey.pem").read_text())


def configure_provider_creds():
    """Configure DNS credentials if required"""
    verification_method = os.environ.get(ENV_VERIFICATION_METHOD, "http")
    if verification_method == "dns":
        dns_provider = os.environ.get(ENV_DNS_PROVIDER)
        if dns_provider == "google":
            service_account = os.environ.get(ENV_GCE_SERVICE_ACCOUNT, "")
            if len(service_account) == 0:
                raise Exception("GCE_SERVICE_ACCOUNT is not defined")
            else:
                with open(DEFAULT_GCE_CREDENTIALS, "w+") as creds_file:
                    creds_file.write(service_account)

                os.chown(DEFAULT_GCE_CREDENTIALS, 0, 0)
                os.chmod(DEFAULT_GCE_CREDENTIALS, stat.S_IREAD)
                print("Creating GCE Service Account file", flush=True)
        elif dns_provider == "route53":
            if len(os.environ.get("AWS_ACCESS_KEY_ID", "")) == 0 or len(
                    os.environ.get("AWS_SECRET_ACCESS_KEY", "")) == 0:
                raise Exception("AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY is not defined")
        else:
            raise Exception("Unknown DNS provider")
    elif verification_method != "http":
        raise Exception("Unknown verification method: " + verification_method)


def get_domains():
    """Retrieve list of domains from own app definition or from environment variable based on verification method"""
    data = get_marathon_app(os.environ.get(ENV_MARATHON_APP_ID))
    verification_method = os.environ.get(ENV_VERIFICATION_METHOD, "http")
    if verification_method == "http":
        return data["app"]["labels"]["HAPROXY_0_VHOST"]
    elif verification_method == "dns":
        return os.environ.get(ENV_DOMAINS)
    else:
        raise Exception("Unknown verification method: " + verification_method)


def get_cert_filepath(domain_name):
    """Retrieve the certificate path based on the domain name"""
    domain_name = rewrite_domain_name(domain_name)
    latest_cert_dir = find_newest_dir(domain_name)
    return f"{latest_cert_dir}/{domain_name}.pem"


def update_marathon_app(app_id, **kwargs):
    """Post new certificate data (as environment variable) to marathon to update the marathon-lb app definition"""
    print("Uploading certificates", flush=True)

    data = kwargs.copy()
    data['id'] = app_id
    headers = {'Content-Type': 'application/json'}
    response = requests.put(f"{get_marathon_url()}/v2/apps/{app_id}",headers=headers,
                            data=json.dumps(data), verify=False)
    if not response.ok:
        print(response)
        print(response.text, flush=True)
        raise Exception("Could not update app. See response text for error message.")
    data = response.json()
    # if not "deploymentId" in data:
    if "deploymentId" not in data:
        print(data, flush=True)
        raise Exception("Could not update app. Marathon did not return deployment id. Please see error message.")
    deployment_id = data['deploymentId']

    # Wait for deployment to complete
    deployment_exists = True
    sum_wait_time = 0
    sleep_time = 5
    while deployment_exists:
        time.sleep(sleep_time)
        sum_wait_time += sleep_time
        print("Waiting for deployment to complete", flush=True)
        # Retrieve list of running deployments
        response = requests.get(f"{get_marathon_url()}/v2/deployments", verify=False)
        deployments = response.json()
        deployment_exists = False
        for deployment in deployments:
            # Check if our deployment is still in the list
            if deployment['id'] == deployment_id:
                deployment_exists = True
                break
        if deployment_exists and sum_wait_time > 60 * sleep_time:
            raise Exception("Failed to update app due to timeout in deployment.")
    print("Successfully uploaded certificates", flush=True)


def generate_letsencrypt_cert(domains):
    """Use Certbot to validate domains and retrieve LetsEncrypt certificates"""
    domains_changed = domains != read_domains_from_last_time()
    domain_list = domains.split(",")
    first_domain = domain_list[0]
    certbot_args = list()

    for domain in domain_list:
        certbot_args.append("-d")
        certbot_args.append(domain)

    verification_method = os.environ.get(ENV_VERIFICATION_METHOD, "http")
    if verification_method == "http":
        certbot_args = certbot_args + CERTBOT_ARGS_HTTP
    elif verification_method == "dns":
        certbot_args = certbot_args + CERTBOT_ARGS_DNS
        dns_provider = os.environ.get(ENV_DNS_PROVIDER, "google")
        if dns_provider == "google":
            certbot_args = certbot_args + CERTBOT_ARGS_DNS_GCLOUD
        elif dns_provider == "route53":
            certbot_args = certbot_args + CERTBOT_ARGS_DNS_ROUTE53
        else:
            raise Exception("Unknown DNS provider: " + dns_provider)

    """Check if we already have a certificate"""
    if not domains_changed and os.path.exists(f"{CERTIFICATES_DIR}/{first_domain}/{first_domain}.pem"):
        print("About to attempt renewal of certificate", flush=True)
        certbot_args = ["certbot", "renew"]
    else:
        print("Running certbot to generate initial signed cert", flush=True)
        print(f"Using server {get_letsencrypt_url()}", flush=True)
        certbot_args = DEFAULT_CERTBOT_ARGS + certbot_args

    """Run Certbot with the configured arguments"""
    print("Running the following command:")
    print(*certbot_args, flush=True)
    result = subprocess.run(certbot_args)
    if result.returncode != 0:
        print(result, flush=True)
        raise Exception("Obtaining certificates failed. Check Certbot output for error messages.")
    write_domains_to_file(domains)

    """Create the combined cert used by marathon-lb"""
    write_combined_cert_to_file(first_domain)
    return first_domain


def upload_cert_to_marathon_lb(cert_filename):
    """Update the marathon-lb app definition and set the the generated certificate
       as environment variable HAPROXY_SSL_CERT
    """
    print("Retrieving current marathon-lb cert", flush=True)
    with open(cert_filename) as cert_file:
        cert_data = cert_file.read()
    # Retrieve current app definition of marathon-lb
    marathon_lb_id = os.environ.get(ENV_MARATHON_LB_ID)
    app_data = get_marathon_app(marathon_lb_id)
    env = app_data["app"]["env"]
    # Compare old and new certs
    if env.get(ENV_MARATHON_LB_CERT, "") != cert_data:
        print("Certificate changed. Updating certificate", flush=True)
        env[ENV_MARATHON_LB_CERT] = cert_data
        update_marathon_app(marathon_lb_id, env=env, secrets=app_data["app"].get("secrets", {}))
    else:
        print("Certificate not changed. Not doing anything", flush=True)


def run_client():
    """Generate certificates if necessary and update marathon-lb"""
    domains = get_domains()
    print("Requesting certificates for " + domains, flush=True)
    domain_name = generate_letsencrypt_cert(domains)
    cert_file = get_cert_filepath(domain_name)
    upload_cert_to_marathon_lb(cert_file)


def run_client_with_backoff():
    """Calls run_client but catches exceptions and tries again for up to one hour.
        Use this variant if you don't want this app to fail (and redeploy) because of intermittent errors.
    """
    backoff_seconds = 30
    sum_wait_time = 0
    while True:
        try:
            run_client()
            return
        except Exception as ex:
            print(ex)
            if sum_wait_time >= 60 * 60:
                # Reraise exception after 1 hour backoff, will lead to task failure in marathon
                raise ex
            sum_wait_time += backoff_seconds
            time.sleep(backoff_seconds)
            backoff_seconds *= 2


if __name__ == "__main__":
    """Get the credentials for DNS provider"""
    configure_provider_creds()

    if len(sys.argv) > 1 and sys.argv[1] == "service":
        while True:
            run_client()
            time.sleep(24 * 60 * 60)  # Sleep for 24 hours
    elif len(sys.argv) > 1 and sys.argv[1] == "service_with_backoff":
        while True:
            run_client_with_backoff()
            time.sleep(24 * 60 * 60)  # Sleep for 24 hours
    else:
        run_client()
