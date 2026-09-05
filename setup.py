from setuptools import setup, find_packages

setup(
    name='llmtest',
    version='1.0.6',
    description='Ultra-fast CLI tool for benchmarking LLM latency, TTFT, and throughput',
    author='Mijanur Rahman',
    author_email='hello@mijanpro.com',
    url='https://github.com/mijanlab/LLMtest',
    packages=find_packages(),
    install_requires=[
        'requests>=2.28.0'
    ],
    entry_points={
        'console_scripts': [
            'llmtest=llmtest.cli:main',
            'llm-test=llmtest.cli:main'
        ]
    },
    python_requires='>=3.8',
)

