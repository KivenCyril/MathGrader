FROM maven:3.9.9-eclipse-temurin-17 AS builder

WORKDIR /build

COPY pom.xml ./
COPY src ./src

RUN mvn -DskipTests package && \
    find target -maxdepth 1 -type f -name "*.jar" ! -name "*.jar.original" -exec cp {} /build/app.jar \;

FROM eclipse-temurin:17-jre

WORKDIR /app

COPY --from=builder /build/app.jar /app/app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
