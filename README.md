# РСОИ, ЛР4: деплой микросервисов в Kubernetes

![Python](https://img.shields.io/badge/Python-FastAPI-009688?logo=fastapi&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-Helm-326CE5?logo=kubernetes&logoColor=white)
![Docker Hub](https://img.shields.io/badge/Docker_Hub-images-2496ED?logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-CI%2FCD-2088FF?logo=githubactions&logoColor=white)

Лабораторная работа №4 по курсу «Распределённые системы обработки информации», МГТУ им. Н.Э. Баумана (осень 2025).

> **Код решения — в ветке [`test`](https://github.com/gfdXX/lab4-template/tree/test).**
> В `master` лежит исходный шаблон курса, условие задания — в [ASSIGNMENT.md](ASSIGNMENT.md).

## Что сделано

Сервис аренды автомобилей из [ЛР2](https://github.com/gfdXX/lab2-template) развёрнут в managed-кластере Kubernetes:

- **Helm-чарты** (`helm/`): один универсальный `service-chart` (Deployment, Service, Ingress) для всех четырёх сервисов, отличия задаются файлами `helm/values/*.yaml`; отдельный `postgres-chart` с PVC, ConfigMap и Job для создания баз;
- **Ingress** — единственная точка публикации сервисов наружу;
- **CI/CD в GitHub Actions**: unit-тесты → сборка и публикация образов в Docker Hub → `helm upgrade --install` в кластер (kubeconfig берётся из секретов репозитория) → автопроверка API курса через `port-forward` к Gateway;
- у каждого сервиса своя логическая база в одном экземпляре PostgreSQL.

## Запуск

Локально — как в ЛР2:

```bash
git clone -b test https://github.com/gfdXX/lab4-template.git
cd lab4-template
docker compose up --build
```

В кластер (нужны `kubectl` и `helm` с доступом к кластеру):

```bash
helm upgrade --install postgres ./helm/postgres-chart -n test --create-namespace
helm upgrade --install gateway-service ./helm/service-chart -f helm/values/gateway-service.yaml -n test
```

Остальные сервисы ставятся тем же чартом со своими файлами значений.

## Автор

Салженикин Даниил, МГТУ им. Н.Э. Баумана.
