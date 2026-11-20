# Multi-stage build: compile with the JDK, run with the (smaller) JRE. No Maven: plain javac.
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY src/*.java .
RUN javac -encoding UTF-8 -d /out *.java

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /out /app
EXPOSE 9443
CMD ["java", "-cp", "/app", "LegacyBank"]
