
# KSQLDB UPGRADE 0.21 to 0.26

## Demo

The components we'll use for the demo
- ksqlDB
- connect
- schema-registry
- broker
- zookeeper

The scenario
1. Create topic
    ```
    kafka-topics --bootstrap-server broker:9092 --create --topic events
    ```
2. Insert demo data
   
    Start a console producer
    ```
    kafka-console-producer --bootstrap-server broker:9092 --topic events --property parse.key=true --property key.separator=:
    ```
    
    Demo data with json format, key seperated by `":"`
    ```
    alice:{"name": "alice", "gender": "f", "balance": 1000}
    bob:{"name": "bob", "gender": "m", "balance": 99999}
    alice:{"name": "alice", "gender": "f", "balance": 888}
    ```
    
    Check what's inside
    ```
    kafka-console-consumer --bootstrap-server broker:9092 --topic  events --from-beginning --property print.key=true
    ```
3. Demo source stream/tables
    
    Start ksql-cli
    ```
    docker exec -it ksqldb-cli ksql http://ksqldb-server:8088
    ```

    Create streams/tables
    ```
    # normal stream/table
    create stream s (name varchar key, gender varchar, balance bigint) with (kafka_topic='events', value_format='json');
    create table t (name varchar primary key, gender varchar, balance bigint) with (kafka_topic='events', value_format='json');

    # source stream/table
    create source stream ss (name varchar key, gender varchar, balance bigint) with (kafka_topic='events', value_format='json');
    create source table st (name varchar primary key, gender varchar, balance bigint) with (kafka_topic='events', value_format='json');
    ```

    Difference of sourced stream/table
    ```
    # read only 
    insert into s(name,gender,balance) values ('jim', 'f', 100);
    insert into ss(name,gender,balance) values ('jim', 'f', 100); <-----ERROR, source stream/table is readonly.

    # pull query
    select * from st;
    select * from ss; <-----DOES NOT support pull for stream
    ```

4. Demo Expose Kafka headers to ksqlDB
    
    Run `produce_event_with_header.py` to produce data with headres
    ```
    python produce_event_with_header.py
    ```

    Run consumer or streams/tables from ksqlDB to see the impacts.
    ```
    (...)
    ```

    Create new streams to mapping headers
    ```
    create stream sh (
        name varchar key, 
        gender varchar, 
        balance bigint, 
        h array<struct<key string, value bytes>> headers
    ) with (kafka_topic='events', value_format='json');
    ```

    Extract header from bytes
    ```
    select from_bytes(h[1]->value, 'ascii') from sh where array_length(h) > 0;
    ```

    Produce data with headers into stream
    ```
    insert into sh (name, gender, balance, h) values ('tom', 'm', 90, array[]); <------ERROR, headers are read only.
    ```

5. Demo ksqlDB connect support

    Install connector for the demo
    ```
    confluent-hub install confluentinc/kafka-connect-mqtt:latest --component-dir confluent-hub-components
    ```

    REF: connector json
    ```
    {
        "name": "mqtt-source",
        "config": {
            "connector.class": "MqttSource",
            "name": "mqtt-source",
            "kafka.topic": "bus_raw",
            "mqtt.server.uri": "tcp://mqtt.hsl.fi:1883",
            "mqtt.clean.session.enabled": "false",
            "mqtt.topics": "/hfp/v2/journey/ongoing/vp/bus/#",
            "tasks.max": "1"
        }
    }
    ```

    Create connector from ksqlDB
    ```
    create source connector mqttSource with (
        "connector.class"='MqttSource',
        "confluent.topic.bootstrap.servers"='broker:9092',
        "name"='mqtt-source',
        "kafka.topic"='bus_raw',
        "mqtt.server.uri"='tcp://mqtt.hsl.fi:1883',
        "mqtt.clean.session.enabled"='false',
        "mqtt.topics"='/hfp/v2/journey/ongoing/vp/bus/#',
        "tasks.max"='1'
    );
    ```

    Play with the data inside - https://github.com/confluentinc/apac-workshops/blob/master/mqttdemo-cc/ksql-statements.sql
    ```
    (...)
    ```

7. Event/Process time, Demo re-enable GRACE period with new stream-stream joins semantics
    
    Case1: fail to do stream-table join
    ```
    SET 'auto.offset.reset' = 'earliest';
    SET 'max.task.idle.ms' = '0';

    # create dim table and event stream
    create table dim (id integer primary key, val varchar, ts varchar) with (
        value_format='delimited', partitions=1, kafka_topic='dim');
    create stream event (id integer key, val varchar, ts varchar) with (
        value_format='delimited', partitions=1, kafka_topic='event');

    # data ingestion
    insert into dim (id, val, ts) values (1, 'val2', '2022-05-09 02:00:00');
    insert into event (id, val, ts) values (1, 'val1', '2022-05-09 01:00:00');
    insert into event (id, val, ts) values (1, 'val3', '2022-05-09 03:00:00');

    # stream should able to join table 
    select * from event e left join dim d on e.id=d.id emit changes;


    # HOW to fix - give a timestamp and timestamp_format in with(...)
    create table dim (id integer primary key, val varchar, ts varchar) with (
        timestamp = 'ts', timestamp_format='yyyy-MM-dd HH:mm:ss', value_format='delimited', partitions=1, kafka_topic='dim');
    create stream event (id integer key, val varchar, ts varchar) with (
        timestamp = 'ts', timestamp_format='yyyy-MM-dd HH:mm:ss', value_format='delimited', partitions=1, kafka_topic='event');
    ```

    Case2: Aggregate late coming data
    ```
    # create event stream
    create stream event_demo_late (id integer key, val varchar, ts varchar) with (
        timestamp = 'ts', timestamp_format='yyyy-MM-dd HH:mm:ss', value_format='delimited', partitions=1, kafka_topic='event_demo_late');
    
    # insert data
    insert into event_demo_late (id, val, ts) values (1, 'val1', '2022-05-09 01:00:00');
    insert into event_demo_late (id, val, ts) values (1, 'val1', '2022-05-09 01:59:00');
    insert into event_demo_late (id, val, ts) values (1, 'val1', '2022-05-09 09:00:00');
    insert into event_demo_late (id, val, ts) values (1, 'val1', '2022-05-09 01:59:00');
    insert into event_demo_late (id, val, ts) values (1, 'val1', '2022-05-09 09:01:00');

    # grace period 0 hour
    select from_unixtime(WINDOWSTART), from_unixtime(WINDOWEND), id, count(*) from event_demo_late window tumbling (
        size 1 hour, grace period 0 hour) group by id emit changes;

    # grace period 12 hour
    select from_unixtime(WINDOWSTART), from_unixtime(WINDOWEND), id, count(*) from event_demo_late window tumbling (
        size 1 hour, grace period 12 hour) group by id emit changes;
    ```

    Refernence:
       - https://www.confluent.io/kafka-summit-san-francisco-2019/whats-the-time-and-why/


8. TODO: UDAF

    ```
    ```


## Main features:

0.22.0 
- Add SOURCE streams/tables (#8085,#8063,#8061,#8004,#7945,#8022,#8043,#8009) https://docs.ksqldb.io/en/0.26.0-ksqldb/developer-guide/ksqldb-reference/create-table/#source-tables
- Add pull queries on streams (#8126,#8168,#8124,#8143,#8115,#8064,#8045)
https://docs.ksqldb.io/en/0.26.0-ksqldb/developer-guide/ksqldb-reference/select-pull-query/
- Optimize key-range queries in pull queries (#7993)
https://docs.ksqldb.io/en/0.26.0-ksqldb/developer-guide/ksqldb-reference/select-pull-query/#pull-queries

0.23.1
- Re-enable GRACE period with new stream-stream joins semantics (#8236)
https://docs.ksqldb.io/en/0.26.0-ksqldb/concepts/time-and-windows-in-ksqldb-queries/#out-of-order-events

0.24.0
- Add support for connect specific https configs (#8553)
https://docs.ksqldb.io/en/0.26.0-ksqldb/developer-guide/ksqldb-reference/create-connector/#create-connector
- Pull query LIMIT clause (#8333)
https://docs.ksqldb.io/en/0.26.0-ksqldb/developer-guide/ksqldb-reference/select-pull-query/#synopsis
- Expose Kafka headers to ksqlDB (#8350,#8366,#8416,#8417,#8475,#8496,#8516)
https://docs.ksqldb.io/en/0.26.0-ksqldb/reference/sql/data-definition/#headers
- Allow schema id in source creation (#8441,#8421,#8411,#8401,#8185,#8572)
https://docs.ksqldb.io/en/0.26.0-ksqldb/operate-and-deploy/schema-inference-with-id/

0.25.1
- Extend Udaf interface to allow for polymorphic UDAFs. (#8871)
- Generalize the UDAFs collect_list and collect_set (#8877)
- Generalize the UDAFs earliest_by_offset and latest_by_offset (#8878)

0.26.0
- Add support for Stream-Stream and Table-Table right join (#8845)
Support MIN/MAX udafs for Time/TS/Date types (#8924)

## References:
- ksql/CHANGELOG.md at master · confluentinc/ksql · GitHub