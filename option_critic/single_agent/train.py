import sys

import gym
import numpy as np
import torch
from matplotlib import pyplot as plt

from envs.FourRooms import FourRoomsController, FourRooms
from pettingzoo.mpe import simple_spread_v2
from option_critic.single_agent.singleAgent import OptionCriticAgent
import torch.optim as optim
from option_critic.utils.experience_replay import ReplayBuffer

rooms = [
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]
]
timeout = 1000

controls = {
    0: (-1, 0),  # 'LEFT'
    1: (1, 0),  # 'RIGHT'
    2: (0, -1),  # 'DOWN'
    3: (0, 1),  # 'UP'
}


def train(env, learning_rate, num_steps):
    agent = OptionCriticAgent(in_features=env.observation_space.shape[0],
                              num_actions=env.action_space.n,
                              num_options=4,
                              )

    # Use Adam optimizer because it should converge faster than SGD and generalization may not be super important
    oc_optimizer = optim.RMSprop(agent.parameters(), lr=learning_rate)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # No of steps before critic update
    update_frequency = 4
    target_update_frequency = 200

    buffer = ReplayBuffer(50000)

    state, _ = env.reset()
    rewards = []
    train_returns = []
    train_loss = []
    episode_length = []
    episode = 0
    steps = 0
    prev_steps = 0
    while episode < 2000:
        steps += 1
        action, beta_w, log_prob, entropy, Q = agent.forward(state)

        new_state, reward, done, _, _ = env.step(action)

        buffer.push(state, agent.current_option, reward, new_state, done)

        rewards.append(reward)

        state = new_state

        with torch.no_grad():
            td_target = agent.compute_td_target(reward, done, new_state, beta_w)

        actor_loss = agent.actor_loss(td_target, log_prob, entropy, beta_w, Q)
        critic_loss = torch.tensor([0])

        if len(buffer) > 32:

            if steps % update_frequency == 0:
                data_batch = buffer.sample(32)
                critic_loss = agent.critic_loss(data_batch)
                # print(f"Critic loss:{critic_loss}")

        # print(f"Actor loss:{actor_loss}")
        loss = actor_loss + critic_loss
        train_loss.append(loss.detach().cpu().numpy())
        oc_optimizer.zero_grad(True)
        loss.backward()
        oc_optimizer.step()

        if steps % target_update_frequency == 0:
            agent.update_target_net()

        if done:
            episode += 1
            episode_length.append(steps - prev_steps)
            prev_steps = steps
            G = 0
            for r in reversed(rewards):
                G = r + 0.99 * G
            train_returns.append(G)
            rewards = []
            state, _ = env.reset()

            if True:  # episode % 10 == 0:
                print("Eps:", agent.eps)
                sys.stdout.write("episode: {}, return: {} , steps: {}\n".format(episode, G, steps))
    torch.save(agent.state_dict(), "outputs/model_checkpoint.pt")

    return train_returns, train_loss, episode_length


def visualize_rollout():
    import matplotlib.patches as mpatches
    env = FourRoomsController(FourRooms(rooms, timeout=timeout), controls=controls)

    agent = OptionCriticAgent(in_features=env.observation_space.shape[0],
                              num_actions=env.action_space.n,
                              num_options=4,
                              )
    agent.load_state_dict(torch.load("outputs/model_checkpoint.pt"))

    # Heatmap for state values
    value_heatmap = np.array([[-10 for i in range(11)] for j in range(11)])
    option_heatmap = np.array([[-1 for i in range(11)] for j in range(11)])
    for i in range(11):
        for j in range(11):
            if rooms[i][j] == 1:
                print(i,j)
                continue
            state = np.array((i, j))
            f = agent.get_features(state)
            q = agent.get_Q(f)
            v = q.max(-1)[0].detach().numpy()
            option, _ = agent.get_option(q, f)
            value_heatmap[i][j] = v
            option_heatmap[i][j] = option

    plt.imshow(value_heatmap)
    plt.show()

    img2 = plt.imshow(option_heatmap)
    values = np.unique(option_heatmap.ravel())
    colors = [img2.cmap(img2.norm(value)) for value in values]
    patches = [mpatches.Patch(color=colors[i], label="Option {l}".format(l=i)) for i in range(1, len(values))]
    # put those patched as legend-handles into the legend
    plt.legend(handles=patches, loc="center left", bbox_to_anchor=(1, 0.5), borderaxespad=0.)
    plt.imshow(option_heatmap)
    plt.show()

    arr = rooms.copy()
    done = False
    state, _ = env.reset()
    time = 0
    rewards = []

    while not done:
        # Get next action by greedy
        arr[state[0]][state[1]] = 3
        action, _, _, _, _ = agent.forward(state)
        next_s, reward, done, _, _ = env.step(action)
        state = next_s
        rewards.append(reward)
        time += 1

    G = 0
    for r in reversed(rewards):
        G = r + 0.99 * G
    print(f"Return: {G} , Time:{time}")
    plt.imshow(arr)
    plt.show()


def plot_curves(arr_list, legend_list, color_list, xlabel, ylabel, fig_title):
    """
    Args:
        arr_list (list): list of results arrays to plot
        legend_list (list): list of legends corresponding to each result array
        color_list (list): list of color corresponding to each result array
        ylabel (string): label of the Y axis

        Note that, make sure the elements in the arr_list, legend_list and color_list are associated with each other correctly.
        Do not forget to change the ylabel for different plots.
    """
    # set the figure type
    fig, ax = plt.subplots(figsize=(12, 8))

    # PLEASE NOTE: Change the labels for different plots
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)

    # ploth results
    h_list = []

    for arr, legend, color in zip(arr_list, legend_list, color_list):
        # compute the standard error
        arr = arr.astype(float)
        arr_err = arr.std(axis=0) / np.sqrt(arr.shape[0])
        # plot the mean
        h, = ax.plot(range(arr.shape[1]), arr.mean(axis=0), color=color, label=legend)
        # plot the confidence band
        arr_err *= 1.96
        ax.fill_between(range(arr.shape[1]), arr.mean(axis=0) - arr_err, arr.mean(axis=0) + arr_err, alpha=0.3,
                        color=color)
        # save the plot handle
        h_list.append(h)

    # plot legends
    ax.set_title(f"{fig_title}")
    ax.legend(handles=h_list)

    # save the figure
    plt.savefig(f"{fig_title}.png", dpi=200)

    plt.show()


if __name__ == '__main__':
    # env = simple_spread_v2.parallel_env(N=1, local_ratio=0.2, max_cycles=25, continuous_actions=False,
    #                                     render_mode=None)

    # num_trials = 5
    # all_returns = []
    # all_losses = []
    # all_lengths = []
    # for i in range(num_trials):
    #     env = FourRoomsController(FourRooms(rooms, timeout=timeout), controls=controls)
    #     # env = gym.make("CartPole-v0")
    #     train_returns, train_loss, episode_length = train(env, learning_rate=0.0005, num_steps=100_000)
    #     all_returns.append(train_returns)
    #     all_losses.append(train_loss)
    #     all_lengths.append(episode_length)

    # np.save("outputs/train_returns", all_returns)
    # np.save("outputs/train_loss", all_losses)
    # np.save("outputs/episode_length", all_lengths)
    # all_returns = np.load("outputs/train_returns.npy", allow_pickle=True)
    # all_losses = np.load("outputs/train_loss.npy", allow_pickle=True)
    # all_lengths = np.load("outputs/episode_length.npy", allow_pickle=True)
    #
    # plot_curves([np.array(all_returns)],
    #             ["Returns Averaged over 5 trials"],
    #             ["b"],
    #             "Episodes",
    #             "Averaged discounted return", "Returns Over 5 Trails")
    # plot_curves([np.array(all_lengths)],
    #             ["Episode Lengths Averaged over 5 trials"],
    #             ["b"],
    #             "Episodes",
    #             "Averaged Episode Length", "Lengths Over 5 Trails")

    visualize_rollout()
