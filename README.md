# Let's Encrypt DC/OS!

This is a sample [Marathon](https://github.com/mesosphere/marathon) app for encrypting your [Marathon-lb](https://github.com/mesosphere/marathon-lb) HAProxy endpoints using [Let's Encrypt](https://letsencrypt.org/). With this, you can automatically generate and renew valid SSL certs with Marathon-lb.

## Getting started

Ensure you have **at least 2 or more** public agents in your DC/OS cluster, and that marathon-lb is scaled out to more than 1 public agent. Deploying this app requires this since it entails restarting marathon-lb.
Wildcard certificates are only supported when `LETSENCRYPT_VERIFICATION_METHOD` is set to **dns**, `DNS_PROVIDER` is set to **google** or **route53** and the required credentials are defined for either provider.

### HTTP Verfication

Clone (or manually copy) this repo, and modify the [letsencrypt-dcos-http.json](letsencrypt-dcos-http.json) file to include:
 - The list of hostnames (must be FQDNs) for which you want to generate SSL certs (in `HAPROXY_0_VHOST`)
 - An admin email address for your certificate (in `LETSENCRYPT_EMAIL`)
 - The Marathon API endpoint (in `MARATHON_URL`)
 - The Marathon-lb app ID (in `MARATHON_LB_ID`)
 
### Google DNS Verification

Clone (or manually copy) this repo, and modify the [letsencrypt-dcos-dns-google.json](letsencrypt-dcos-dns-google.json) file to include:
- The list of hostnames (must be FQDNS) for which you want to generate SSL certs (in `DOMAINS`)
- An admin email address for your certificate (in `LETSENCRYPT_EMAIL`)
- The verification method should be set to `dns` (in `LETSENCRYPT_VERIFICATION_METHOD`)
- The DNS provider should be set to `google` (in `DNS_PROVIDER`)
- Reference the GCP Service Account private JSON key, stored as a DCOS Secret (in `GCE_SERVICE_ACCOUNT`)
- The Marathon API endpoint (in `MARATHON_URL`)
- The Marathon-lb app ID (in `MARATHON_LB_ID`)

The GCP Service Account needs the following permissions:

* **dns.changes.create**
* **dns.changes.get**
* **dns.managedZones.list**
* **dns.resourceRecordSets.create**
* **dns.resourceRecordSets.delete**
* **dns.resourceRecordSets.list**
* **dns.resourceRecordSets.update**

### AWS DNS Verification

Clone (or manually copy) this repo, and modify the [letsencrypt-dcos-dns-route53.json](letsencrypt-dcos-dns-route53.json) file to include:
- The list of hostnames (must be FQDNS) for which you want to generate SSL certs (in `DOMAINS`)
- An admin email address for your certificate (in `LETSENCRYPT_EMAIL`)
- The verification method should be set to `dns` (in `LETSENCRYPT_VERIFICATION_METHOD`)
- The DNS provider should be set to `route53` (in `DNS_PROVIDER`)
- Add the AWS IAM Account credentials, stored as DCOS Secrets (in `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`)
- The Marathon API endpoint (in `MARATHON_URL`)
- The Marathon-lb app ID (in `MARATHON_LB_ID`)

The AWS IAM account needs the following permissions:

* **route53:ListHostedZones**
* **route53:GetChange**
* **route53:ChangeResourceRecordSets**

This app also supports specifying the Lets Encrypt server, for situations where users may be running their own Boulder server on an internal network, or for using the Lets Encrypt staging servers for testing. By default it is set to the [Lets Encrypt staging server](https://acme-staging-v02.api.letsencrypt.org/directory) , so for production use change the `LETSENCRYPT_SERVER_URL` variable - if you are using the Lets Encrypt servers the default should be https://acme-v02.api.letsencrypt.org/directory

Now launch the `letsencrypt-dcos` Marathon app:

```
$ dcos marathon app add letsencrypt-dcos.json
```

There are 2 test apps included, based on [openresty](https://openresty.org/), which you can use to test everything. Have a look in the `test/` directory within the repo.

## How does it work?

The app includes a script: [`run_cert.py`](run_cert.py). The script will generate the initial SSL cert and POST the cert to Marathon for Marathon-lb. It will then attempt to renew & update the cert every 24 hours. It will compare the current cert in Marathon to the current live cert, and update it as necessary.

A persistent volume called `data` is mounted inside the container at `/etc/letsencrypt` which contains the certificates and other generated state.

## Limitations

 - You may only have up to 100 domains per cert.
 - Let's Encrypt currently has rate limits, such as issuing a maximum of 5 certs per set of domains per week.
 - Currently, when the cert is updated, it requires a full redeploy of Marathon-lb. This means there may be a few seconds of downtime as the deployment occurs. This can be mitigated by placing another LB (such as an ELB or F5) in front of HAProxy.
 - AWS Route53 and GCP DNS are the only supported DNS providers at this time. 