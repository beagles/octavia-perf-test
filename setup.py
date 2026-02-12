#!/usr/bin/env python3
"""Setup script for octavia-perf-test."""

from setuptools import setup, find_packages

setup(
    name="octavia-perf-test",
    version="0.1.0",
    description="Performance testing framework for Octavia amphora driver",
    author="OpenStack Octavia Team",
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "locust>=2.20.0",
        "paramiko>=3.0.0",
        "requests>=2.28.0",
        "sqlalchemy>=2.0.0",
        "PyYAML>=6.0",
        "matplotlib>=3.7.0",
        "jinja2>=3.1.0",
        "click>=8.1.0",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "octavia-perf-test=bin.run_test:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
