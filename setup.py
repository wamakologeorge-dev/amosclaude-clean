from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="amosclaud-ai",
    version="1.0.0",
    author="Amosclaud",
    author_email="owner@amosclaud.ai",
    description="Amosclaud-owned CI/CD, data, tools, resources, and AI automation system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/wamakologeorge-dev/amosclaude-clean",
    packages=find_packages(),
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
            "amosclaud-ai=amoscloud_ai.cli:main",
        ],
    },
)
