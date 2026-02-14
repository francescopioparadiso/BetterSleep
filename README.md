Sure! Here's a **clean, English version** of your workflow with all the fixes applied:

---

# 🟢 Database Service

Go to the Database folder and start Postgres / Mongo with Compose:

```bash
docker compose up -d
```

* `-d` → run in background
* Containers will be attached to the defined network (`bettersleep`)

---

# 🟢 Catalog Service – Build

From the catalog folder:

```bash
docker build -t catalog-service .
```

---

# 🟢 Catalog Service – Run

If **no container with that name exists**:

```bash
docker run \
  --name bs_catalog_1 \
  -p 8080:8080 \
  catalog-service
```

If a container already exists, stop and remove it first:

```bash
docker stop bs_catalog_1
docker rm bs_catalog_1
```

Then run the command above again.

> ✅ Note: the catalog listens on `0.0.0.0:8080` → host port must match container port (`-p 8080:8080`).

---

# 🟢 Catalog Service – Multiple Instances

If you want multiple catalog instances, change:

* Container name (`bs_catalog_2`, `bs_catalog_3`, …)
* Host port (`-p 8001:8080`, `-p 8002:8080`, …)

Example:

```bash
docker run -d \
  --name bs_catalog_2 \
  --network bettersleep \
  -p 8001:8080 \
  catalog-service
```

---

# 🟢 Stop & Remove Everything

For a single container:

```bash
docker stop bs_catalog_1
docker rm bs_catalog_1
```

For Compose (Postgres / Mongo):

```bash
docker compose down
```

To also remove volumes:

```bash
docker compose down -v
```

---

If you want, I can also write a **single bash script** that:

1. Stops all catalog containers
2. Removes old containers
3. Builds the catalog image
4. Runs the catalog on the correct port

…so you don’t have to do everything manually every time 💪

Do you want me to create that script?
