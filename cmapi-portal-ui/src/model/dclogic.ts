// The base class the mockup's logic expects. State merges at once and listeners run after, as on the canvas.
type Listener = () => void;

export class DCLogic<Props = Record<string, unknown>, State = any> {
  props: Props;
  state = {} as State;
  private listeners = new Set<Listener>();

  constructor(props: Props) {
    this.props = props;
  }

  setState(update: Partial<State>): void {
    this.state = { ...this.state, ...update };
    this.listeners.forEach((listener) => listener());
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
