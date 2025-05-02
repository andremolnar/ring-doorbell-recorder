from setuptools import setup, find_packages

setup(
    name="myringdoorbell",
    version="0.1.0",
    description="Ring Doorbell Capture Application",
    author="Andre Molnar",
    packages=find_packages(),
    package_data={
        "": ["*.yml", "*.json"],
    },
    include_package_data=True,
    install_requires=[
        "ring_doorbell",
        "pyee",
        "structlog",
        "aiosqlite",
        "sqlalchemy",
        "pydantic",
        "fastapi",
        "uvicorn",
        "python-dotenv",
        "fsspec",  # Adding fsspec as a dependency
    ],
    entry_points={
        "console_scripts": [
            "myringdoorbell=src.main:main",
        ],
    },
    python_requires=">=3.8",
)
