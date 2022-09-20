"""
A helper script to produce event into Kafka with headers.
"""


import json

from confluent_kafka import SerializingProducer

conf = {'bootstrap.servers': 'broker:9092'}

# initialize producer instance
producer = SerializingProducer(conf)

producer.produce(
    topic='events',
    key='jim',
    value=json.dumps({'name': 'jim', 'gender': 'f', 'balance': 99999}).encode(),
    headers=[('tag1', 'xxx1'), ('tag2', 'xxx2')]
)
producer.poll(0)
producer.flush()

print('done')
