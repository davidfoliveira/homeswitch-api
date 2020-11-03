"""
The homeswitch-api setup module.

See: https://github.com/davidfoliveira/homeswitch-api
"""
import os

from setuptools import setup
from pip._internal.req import parse_requirements
from pip._internal.network.session import PipSession


def get_requirements():
    """Parse requirements from requirements.txt."""
    parsed_requirements = parse_requirements(
        'requirements.txt',
        session=PipSession(),
    )
    return [str(ir.requirement) for ir in parsed_requirements if ir.requirement is not None]


with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="homeswitch-api",
    version="0.0.1",
    author="David Oliveira",
    author_email="d.oliveira@prozone.org",
    description="An API for your home smart switches",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/davidfoliveira/homeswitch-api",
    classifiers=[
        "Programming Language :: Python :: 2",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=2.7',
    packages=['homeswitch'],
    install_requires=get_requirements(),
    entry_points={
        'console_scripts': [
            'hsapid=homeswitch.api:main',
            'hslookupd=homeswitch.devices:main',
        ],
    },
)
