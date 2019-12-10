#!/usr/bin/env python
import json
import socket
import time
import requests

import boto3


class EC2Metadata(object):
    """
    Class for querying metadata from EC2.
    """

    METAOPTS = [
        'ami-id',
        'ami-launch-index',
        'ami-manifest-path',
        'ancestor-ami-id',
        'availability-zone',
        'block-device-mapping',
        'instance-id',
        'instance-type',
        'region',
        'local-hostname',
        'local-ipv4',
        'kernel-id',
        'product-codes',
        'public-hostname',
        'public-ipv4',
        'public-keys',
        'ramdisk-id',
        'reserveration-id',
        'security-groups',
        'user-data'
    ]

    def __init__(self, addr='169.254.169.254', api='latest'):
        self.ec2 = boto3.resource('ec2')
        self.addr = addr
        self.api = api
        if not self._test_connectivity(self.addr, 80):
            raise Exception("could not establish connection to: {0}".format(self.addr))

    @staticmethod
    def _test_connectivity(addr, port):
        for i in range(6):
            s = socket.socket()
            try:
                s.connect((addr, port))
                s.close()
                return True
            except socket.error:
                time.sleep(1)
        return False

    def _get(self, uri):
        """
        Make the request to the metadata URL.
        """
        url = 'http://{}/{}/{}/'.format(self.addr, self.api, uri)
        response = requests.get(url)
        if "404 - Not Found" in response.text:
            return None
        return response.text

    def get(self, name):
        if name == 'availability-zone':
            return self._get('meta-data/placement/availability-zone')

        if name == 'public-keys':
            data = self._get('meta-data/public-keys')
            keyids = [line.split('=')[0] for line in data.splitlines()]
            public_keys = []
            for keyid in keyids:
                uri = 'meta-data/public-keys/%d/openssh-key' % int(keyid)
                public_keys.append(self._get(uri).rstrip())
            return public_keys

        if name == 'user-data':
            return self._get('user-data')

        if name == 'region':
            return json.loads(self._get('dynamic/instance-identity/document'))['region']

        return self._get('meta-data/' + name)
