FROM eclipse-temurin:21-jdk-jammy

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates maven tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 amosclaud \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin amosclaud \
    && mkdir -p /workspace /artifacts /home/amosclaud/.m2 /home/amosclaud/.gradle \
    && chown -R amosclaud:amosclaud /workspace /artifacts /home/amosclaud

COPY --chown=amosclaud:amosclaud entrypoint.sh /usr/local/bin/amosclaud-java-pod
RUN chmod 0555 /usr/local/bin/amosclaud-java-pod

ENV HOME=/home/amosclaud \
    AMOSCLAUD_BUILD_TOOL=auto \
    AMOSCLAUD_JDK=21

WORKDIR /workspace
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/amosclaud-java-pod"]
