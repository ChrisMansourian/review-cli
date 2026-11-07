from setuptools import setup, find_packages

setup(
    name="reviewer",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "reviewer=reviewer.cli:main",
            "reviewer-mcp=reviewer.mcp_server:main",
        ],
    },
)
