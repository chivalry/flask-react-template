import axios from "axios";

const client = axios.create({
  baseURL: "/api",
  timeout: 15_000,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

export default client;
