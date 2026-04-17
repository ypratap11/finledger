FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY src ./src
COPY test ./test
COPY tsconfig.json ./

EXPOSE 3001

ENV DATABASE_URL=postgresql://finledger:finledger@postgres:5432/finledger
ENV STRIPE_WEBHOOK_SECRET=whsec_test
ENV ZUORA_WEBHOOK_SECRET=zuora_test

CMD ["npm", "run", "dev"]
