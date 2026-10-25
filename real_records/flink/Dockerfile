FROM flink:1.19.1-scala_2.12-java11
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv curl && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/pyflink \
 && /opt/pyflink/bin/pip install --no-cache-dir apache-flink==1.19.1 \
 && curl -fL https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/flink-sql-connector-kafka-3.2.0-1.19.jar -o /opt/flink/lib/flink-sql-connector-kafka.jar
COPY real_records /app/real_records
ENV PYTHONPATH=/app
ENV PATH=/opt/pyflink/bin:$PATH
RUN mkdir -p /checkpoints && chown -R flink:flink /checkpoints /app
USER flink
