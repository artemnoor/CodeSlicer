import { Greeter } from "./service";

const prefix = "🚀";
export function useGreeting(name: string): string {
  const greeter = new Greeter();
  return `${prefix} ${greeter.greet(name)}`;
}
