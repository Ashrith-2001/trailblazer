#!/usr/bin/env python3
"""
Trailblazer setup.py - Universal Python package installer
"""

from setuptools import setup, find_packages
from pathlib import Path

this_dir = Path(__file__).resolve().parent
readme_path = this_dir / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

setup(
    name="trailblazer-agent",
    version="1.0.0",
    description="Verified codebase issue investigator and interactive dashboard for AI coding agents and engineers.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Ashrith K",
    author_email="kothaashrith07@gmail.com",
    url="https://github.com/Ashrith-2001/trailblazer",
    license="MIT",
    packages=find_packages(),
    package_data={"trailblazer": ["assets/*"]},
    include_package_data=True,
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "trailblazer=trailblazer.compile:main",
            "trailblazer-mcp=trailblazer.server:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Quality Assurance",
    ],
)
