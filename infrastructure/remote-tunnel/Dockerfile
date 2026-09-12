FROM alpine:3.22
RUN apk add --no-cache openssh-client autossh curl ca-certificates
COPY entrypoint.sh /usr/local/bin/sphere-remote-tunnel
RUN chmod 755 /usr/local/bin/sphere-remote-tunnel
ENTRYPOINT ["/usr/local/bin/sphere-remote-tunnel"]
