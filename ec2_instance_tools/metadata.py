#!/usr/bin/env python
import json
import socket
import time
from typing import Any, Union, List

import boto3
import requests


class EC2Metadata(object):
    """
    Class for querying metadata from EC2.
    """

    METAOPTS = [
        "ami-id",
        "ami-launch-index",
        "ami-manifest-path",
        "ancestor-ami-id",
        "availability-zone",
        "block-device-mapping",
        "instance-id",
        "instance-type",
        "region",
        "local-hostname",
        "local-ipv4",
        "kernel-id",
        "product-codes",
        "public-hostname",
        "public-ipv4",
        "public-keys",
        "ramdisk-id",
        "reserveration-id",
        "security-groups",
        "user-data",
    ]

    def __init__(self, addr: str = "169.254.169.254", api: str = "latest"):
        self.ec2 = boto3.resource("ec2")
        self.addr = addr
        self.api = api
        if not self._test_connectivity(self.addr, 80):
            raise RuntimeError(f"could not establish connection to: {self.addr}")

    @staticmethod
    def _test_connectivity(addr: str, port: int) -> bool:
        """
        Ensure we can connect to the metadata URL.

        Args:
            addr: the metadata address
            port: the metadata port

        Returns:
            ``True`` if we can connect, ``False`` otherwise.
        """
        for _ in range(6):
            s = socket.socket()
            try:
                s.connect((addr, port))
                s.close()
                return True
            except socket.error:
                time.sleep(1)
        return False

    def _get(self, path: str) -> Any:
        """
        Make the request to the metadata URL.

        Args:
            path: the path under the metadata URL to query

        Returns:
            The response body, or ``None`` if the specific metadata
        """
        url = f"http://{self.addr}/{self.api}/{path}/"
        response = requests.get(url, timeout=15)
        if "404 - Not Found" in response.text:
            raise ValueError(f"metadata path not found: {path}")
        return response.text

    def get(self, name: str) -> Union[str, List[str]]:
        """
        Get the value of a metadata key.

        Args:
            name: the name of the metadata key to query

        Returns:
            The value of the metadata key, or ``None`` if the key does not
            exist.
        """
        if name == "availability-zone":
            return self._get("meta-data/placement/availability-zone")

        if name == "public-keys":
            data = self._get("meta-data/public-keys")
            if data is None:
                raise ValueError("could not determine public keys")
            keyids = [line.split("=")[0] for line in data.splitlines()]
            public_keys: List[str] = []
            for keyid in keyids:
                uri = f"meta-data/public-keys/{int(keyid)}/openssh-key"
                public_keys.append(self._get(uri).rstrip())
            return public_keys

        if name == "user-data":
            return self._get("user-data")

        if name == "region":
            data = self._get("meta-data/placement/availability-zone")
            if data:
                return json.loads(
                    self._get("dynamic/instance-identity/document")
                )["region"]
            raise ValueError("could not determine region")

        return self._get("meta-data/" + name)
