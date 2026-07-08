import os
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

requirements = []
if os.path.exists("requirements.txt"):
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="amoscloud-ai",
    version="1.0.0",
    author="Amoscloud Team",
    author_email="dev@amoscloud.ai",
    description="Professional CI/CD & Deployment Automation System",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/wamakologeorge-dev/amosclaude-clean",
    packages=find_packages(exclude=["tests*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: MIT License",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "amoscloud-ai=src.amoscloud_ai.cli:main",
        ],
    },
)
