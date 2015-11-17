package fr.free.hd.ruch.giftsrandomizer.business;

import java.util.Random;

public class JDKRandomGenerator extends Random {
	private static final long serialVersionUID = 7076154990891891220L;

	/** {@inheritDoc} */
	public void setSeed(int seed) {
		setSeed((long) seed);
	}

	/** {@inheritDoc} */
	public void setSeed(int[] seed) {
		// the following number is the largest prime that fits in 32 bits (it is 2^32 - 5)
		final long prime = 4294967291l;

		long combined = 0l;
		for (int s : seed) {
			combined = combined * prime + s;
		}
		setSeed(combined);
	}
}
