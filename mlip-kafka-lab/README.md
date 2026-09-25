# Lab 3: Kafka for Data Streaming

In this lab, you will gain hands-on experience with Apache Kafka, a distributed streaming platform that plays a key role in processing large-scale real-time data. You will establish a connection to a Kafka broker, produce and consume messages, and use Kafka command-line tools.

To receive credit for this lab, you must demonstrate your completed work to the TA during recitation.

## AI Usage Policy

This is an individual graded assignment. AI assistants may be used only for conceptual clarification and debugging guidance. AI assistants should not generate or complete the implementation, modify the starter code, or provide complete solutions to any TODO sections. You are responsible for understanding and writing your own implementation. During the lab demonstration, you may be asked to explain your code and make a small modification to verify your understanding.

Verification: You must be able to explain your implementation and make requested modifications during the TA demonstration. Work that cannot be explained or modified by the student may not receive credit.

## Deliverables
- [ ] Establish a secure SSH tunnel to the Kafka server. Explain to the TA the concepts of topics and offsets in Kafka and how offsets help maintain message continuity if a consumer is disconnected.
- [ ] Modify starter code to implement producer and consumer modes for a Kafka topic.
- [ ] Demonstrate using Kafka's CLI tool *kcat* (or alternatives) to manage and monitor Kafka topics and messages.

## Getting started

Clone the starter code from this Git repository:

```
git clone https://github.com/Srivatsa03/mlip-kafka-lab.git
cd mlip-kafka-lab
```

The repository includes:
- `KafkaDemo.ipynb` — a Python notebook with the Kafka producer and consumer starter code
- [`bug_list.md`](./bug_list.md) — frequent bugs and their solutions

Install the Python client before running the notebook:

```
python -m pip install kafka-python
```

## Connecting to Kafka server

1. Use your UIC NetID to create a secure SSH tunnel to the Kafka server:

   `ssh -o ServerAliveInterval=60 -L 9092:localhost:9092 <NetID>@cs544-f26.cs.uic.edu -NTf`

   Replace `<NetID>` with your UIC NetID and enter your NetID password when prompted. Keep the SSH tunnel active while completing the lab.

2. Test the Kafka server connection to ensure it is operational. For example:

   `kcat -b localhost:9092 -L`

To close the tunnel when you are done:

`lsof -ti:9092 | xargs kill -9`

## Implementing Producer-Consumer Mode

### 1. Producer Mode: Writes Data to Broker

Refer to the TODO sections in the notebook. Edit the bootstrap server address and add 2–3 cities of your choice. Run the code to write messages to the Kafka stream.

### 2. Consumer Mode: Reads Data from Broker

Modify the TODO section by filling in the appropriate parameters/arguments in the starter code. Verify that `kafka_log.csv` is created and contains the consumed messages.

Ref:

[KafkaProducer Documentation](https://kafka-python.readthedocs.io/en/master/apidoc/KafkaProducer.html)

[KafkaConsumer Documentation](https://kafka-python.readthedocs.io/en/master/apidoc/KafkaConsumer.html)

## Using Kafka's CLI tools

`kcat` is a CLI (Command Line Interface). Previously known as kafkacat.

Install with your package installer such as:
- macOS: `brew install kcat`
- Ubuntu: `sudo apt-get install kcat`

Note for Windows Users: You can complete this lab on Windows using WSL (Windows Subsystem for Linux) or Docker. If you use WSL, an Ubuntu environment is recommended for installing and running kcat. Docker can also be used if you already have it set up. The Kafka commands and lab requirements remain the same.

Using the kcat documentation, write and run a command that connects to the local Kafka broker, specifies a topic, and consumes messages from the earliest offset. Be prepared to explain your command during the TA demonstration.

Ref:

[kcat usage](https://docs.confluent.io/platform/current/app-development/kafkacat-usage.html)

[kcat GitHub](https://github.com/edenhill/kcat)

## Additional resources
- [Kafka Introduction Video 1](https://www.youtube.com/watch?v=PzPXRmVHMxI) <- Recommended video for a quick 5-min introduction to Kafka
- [Kafka Introduction Video 2](https://www.youtube.com/watch?v=JalUUBKdcA0)
- [Apache Kafka](https://kafka.apache.org/)
- [Kafka for Beginners](https://www.cloudkarafka.com/blog/2016-11-30-part1-kafka-for-beginners-what-is-apache-kafka.html)
- [What is Apache Kafka? - TIBCO](https://www.tibco.com/reference-center/what-is-apache-kafka)
- [Frequent bug list and solutions](./bug_list.md)
